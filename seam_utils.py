"""Shared validation, conservative cut detection and owned frame caches."""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

MARKER = '.seedance-work.json'
OWNER = {'application': 'seedance-seam-fix', 'version': 1}


def detect_jumps(scores, threshold_sigma=3.0, window=15, min_relative_jump=0.10,
                 recover_periodic=True):
    """Require meaningful amplitude; recover weaker peaks only on a strong grid.

    Recovery requires >=4 strong peaks, >=60% equal adjacent gaps and >=80%
    phase agreement. Every added point must still be a local maximum with
    z >= min(threshold, 1), >=15% excess and >=0.5 absolute grey-level excess.
    """
    scores = np.asarray(scores, dtype=float)
    n = len(scores)
    z = np.zeros(n)
    excess = np.zeros(n)
    relative = np.zeros(n)
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        local = np.delete(scores[lo:hi], i - lo)
        if len(local) < 5:
            continue
        median = np.median(local)
        excess[i] = scores[i] - median
        relative[i] = excess[i] / max(median, 1e-6)
        z[i] = excess[i] / (1.4826 * (np.median(np.abs(local - median)) + 1e-6))
    strong = np.flatnonzero((z > threshold_sigma) & (relative >= min_relative_jump)).tolist()
    recovered = []
    period = None
    if recover_periodic and len(strong) >= 4:
        gaps = np.diff(strong).tolist()
        candidate, count = Counter(gaps).most_common(1)[0]
        if candidate >= 3 and count >= 3 and count / len(gaps) >= 0.60:
            phase, support = Counter(i % candidate for i in strong).most_common(1)[0]
            if support / len(strong) >= 0.80:
                period = candidate
                for i in range(phase, n, period):
                    if (i not in strong and z[i] >= min(threshold_sigma, 1.0)
                            and relative[i] >= max(min_relative_jump, 0.15)
                            and excess[i] >= 0.5
                            and scores[i] >= np.max(scores[max(0, i - 2):min(n, i + 3)])):
                        recovered.append(i)
    return sorted(strong + recovered), {'strong': strong, 'recovered': recovered, 'period': period}


def find_jumps(scores, threshold_sigma=3.0, window=15, min_relative_jump=0.10,
               recover_periodic=True):
    return detect_jumps(scores, threshold_sigma, window, min_relative_jump, recover_periodic)[0]


def relative_jump(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError('Minimum relative increase must be finite and >= 0.')
    return number


def add_detection_options(parser):
    parser.add_argument('--min-relative-jump', type=relative_jump, default=0.10,
                        help='Minimum increase over the local median (0.10 = 10 percent)')
    parser.add_argument('--no-periodic-recovery', action='store_true',
                        help='Do not recover weaker peaks on a confidently detected periodic grid')


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Value must be at least 1.')
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Value must be finite and positive.')
    return number


def frame_indices(value):
    try:
        result = sorted(set(int(x.strip()) for x in value.split(',')))
        if not result or result[0] < 0:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('Specify nonnegative frame indices, e.g. 95,119.')


def validate_frames(indices, count):
    invalid = [i for i in indices if not 0 <= i < count - 1]
    if invalid:
        raise ValueError(f'Invalid seam indices {invalid}; allowed range: 0 to {count - 2}.')


def validate_input(args, parser):
    if not Path(args.input).is_file():
        parser.error(f'Input video is missing: {args.input}')
    if Path(args.input).resolve() == Path(args.output).resolve():
        parser.error('Input and output must be different files.')
    if not 0 <= args.crf <= 51:
        parser.error('--crf must be between 0 and 51.')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            parser.error(f'{tool} is missing from PATH.')
    cap = cv2.VideoCapture(args.input)
    try:
        if not cap.isOpened():
            parser.error('Could not open video.')
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0:
            parser.error('Video has no valid frame rate.')
        if args.frames is not None:
            try:
                validate_frames(args.frames, count)
            except ValueError as exc:
                parser.error(str(exc))
    finally:
        cap.release()


def is_scene_cut(a, b):
    """Require both a large pixel jump and very different colour distributions.

    Deliberately conservative heuristic; manual --frames bypasses it.
    """
    a = cv2.resize(a, (160, 90))
    b = cv2.resize(b, (160, 90))
    difference = float(cv2.absdiff(a, b).mean()) / 255
    histograms = []
    for image in (a, b):
        hist = cv2.calcHist([image], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        histograms.append(cv2.normalize(hist, hist, norm_type=cv2.NORM_L1))
    distance = cv2.compareHist(*histograms, cv2.HISTCMP_BHATTACHARYYA)
    return difference >= 0.30 and distance >= 0.80


def exclude_scene_cuts(path, indices):
    pending = set(indices)
    cuts = set()
    cap = cv2.VideoCapture(str(path))
    previous = None
    index = 0
    try:
        while pending:
            ok, image = cap.read()
            if not ok:
                raise ValueError('Video ends before the seam indices to inspect.')
            if index - 1 in pending:
                if is_scene_cut(previous, image):
                    cuts.add(index - 1)
                pending.remove(index - 1)
            previous = image
            index += 1
    finally:
        cap.release()
    if cuts:
        print(f'Skipped likely scene cuts: {sorted(cuts)}')
    return [i for i in indices if i not in cuts]


def prepare_workdir(path, input_path, output_path):
    raw = Path(path).absolute()
    # Reject symlinks/junctions before resolving them.
    for part in (raw, *raw.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Working-directory path must not contain symlinks or junctions.')
    root = raw.resolve()
    protected = (Path(input_path).resolve(), Path(output_path).resolve(), Path(__file__).resolve().parent)
    if any(p == root or root in p.parents for p in protected):
        raise ValueError('Working directory must not contain the input, output, or project.')
    marker = root / MARKER
    if root.exists() and any(root.iterdir()):
        try:
            if json.loads(marker.read_text(encoding='utf-8')) != OWNER:
                raise ValueError
        except (OSError, ValueError):
            raise ValueError('Unmarked working directory: use a new, empty directory.')
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(OWNER), encoding='utf-8')
    return root


def reset_owned_dir(root, name):
    root = Path(root).resolve()
    if json.loads((root / MARKER).read_text(encoding='utf-8')) != OWNER:
        raise ValueError('Working-directory marker is missing.')
    if name not in {'frames', 'frames_new', 'candidates'}:
        raise ValueError('Unknown working subdirectory.')
    target = root / name
    if target.resolve().parent != root or target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('Unsafe working subdirectory.')
    if target.exists():
        for entry in target.rglob('*'):
            if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                raise ValueError('Link found in working subdirectory; cleanup aborted.')
        shutil.rmtree(target)
    target.mkdir()
    return target


def source_identity(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def cached_frames(root, source, clean=False):
    root = Path(root)
    frames = root / 'frames'
    manifest = root / 'frames.json'
    identity = source_identity(source)
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        entries = data['files']
        valid = (not clean and data['source'] == identity and entries
                 and sorted(entries) == [f'frame_{i:06d}.png' for i in range(1, len(entries) + 1)]
                 and {p.name: p.stat().st_size for p in frames.glob('frame_*.png')} == entries)
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if valid:
        print(f'{len(entries)} fully extracted frames reused from cache.')
        return frames, len(entries)
    frames = reset_owned_dir(root, 'frames')
    manifest.unlink(missing_ok=True)
    print('Extracting original frames ...')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-map', '0:v:0',
                    '-vsync', '0', str(frames / 'frame_%06d.png')], check=True)
    entries = {p.name: p.stat().st_size for p in frames.glob('frame_*.png')}
    if not entries or any(size == 0 for size in entries.values()):
        raise ValueError('No complete frame extraction is available.')
    if source_identity(source) != identity:
        raise ValueError('Input changed during extraction.')
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps({'source': identity, 'files': entries}), encoding='utf-8')
    temporary.replace(manifest)
    return frames, len(entries)
