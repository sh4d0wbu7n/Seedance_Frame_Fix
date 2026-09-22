"""Shared validation, conservative cut detection and owned frame caches."""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

MARKER = '.seedance-work.json'
OWNER = {'application': 'seedance-seam-fix', 'version': 1}


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Wert muss mindestens 1 sein.')
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Wert muss endlich und positiv sein.')
    return number


def frame_indices(value):
    try:
        result = sorted(set(int(x.strip()) for x in value.split(',')))
        if not result or result[0] < 0:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('Frames als nichtnegative Indizes angeben, z.B. 95,119.')


def validate_frames(indices, count):
    invalid = [i for i in indices if not 0 <= i < count - 1]
    if invalid:
        raise ValueError(f'Ungueltige Sprung-Indizes {invalid}; erlaubt: 0 bis {count - 2}.')


def validate_input(args, parser):
    if not Path(args.input).is_file():
        parser.error(f'Eingabevideo fehlt: {args.input}')
    if Path(args.input).resolve() == Path(args.output).resolve():
        parser.error('Eingabe und Ausgabe muessen verschiedene Dateien sein.')
    if not 0 <= args.crf <= 51:
        parser.error('--crf muss zwischen 0 und 51 liegen.')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            parser.error(f'{tool} fehlt im PATH.')
    cap = cv2.VideoCapture(args.input)
    try:
        if not cap.isOpened():
            parser.error('Video kann nicht geoeffnet werden.')
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0:
            parser.error('Video hat keine gueltige Bildrate.')
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
                raise ValueError('Video endet vor den zu pruefenden Sprungstellen.')
            if index - 1 in pending:
                if is_scene_cut(previous, image):
                    cuts.add(index - 1)
                pending.remove(index - 1)
            previous = image
            index += 1
    finally:
        cap.release()
    if cuts:
        print(f'Wahrscheinliche Szenenschnitte ausgelassen: {sorted(cuts)}')
    return [i for i in indices if i not in cuts]


def prepare_workdir(path, input_path, output_path):
    raw = Path(path).absolute()
    # Reject symlinks/junctions before resolving them.
    for part in (raw, *raw.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Workdir darf keine Symlinks oder Junctions enthalten.')
    root = raw.resolve()
    protected = (Path(input_path).resolve(), Path(output_path).resolve(), Path(__file__).resolve().parent)
    if any(p == root or root in p.parents for p in protected):
        raise ValueError('Workdir darf weder Eingabe/Ausgabe noch das Projekt enthalten.')
    marker = root / MARKER
    if root.exists() and any(root.iterdir()):
        try:
            if json.loads(marker.read_text(encoding='utf-8')) != OWNER:
                raise ValueError
        except (OSError, ValueError):
            raise ValueError('Nicht markierter Workdir: bitte einen neuen, leeren Ordner verwenden.')
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(OWNER), encoding='utf-8')
    return root


def reset_owned_dir(root, name):
    root = Path(root).resolve()
    if json.loads((root / MARKER).read_text(encoding='utf-8')) != OWNER:
        raise ValueError('Workdir-Markierung fehlt.')
    if name not in {'frames', 'frames_new', 'candidates'}:
        raise ValueError('Unbekannter Arbeits-Unterordner.')
    target = root / name
    if target.resolve().parent != root or target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('Unsicherer Arbeits-Unterordner.')
    if target.exists():
        for entry in target.rglob('*'):
            if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                raise ValueError('Verknuepfung im Arbeits-Unterordner; Bereinigung abgebrochen.')
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
        print(f'{len(entries)} vollstaendig extrahierte Frames aus Cache verwendet.')
        return frames, len(entries)
    frames = reset_owned_dir(root, 'frames')
    manifest.unlink(missing_ok=True)
    print('Extrahiere Originalframes ...')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-map', '0:v:0',
                    '-vsync', '0', str(frames / 'frame_%06d.png')], check=True)
    entries = {p.name: p.stat().st_size for p in frames.glob('frame_*.png')}
    if not entries or any(size == 0 for size in entries.values()):
        raise ValueError('Keine vollstaendige Frame-Extraktion vorhanden.')
    if source_identity(source) != identity:
        raise ValueError('Eingabe wurde waehrend der Extraktion veraendert.')
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps({'source': identity, 'files': entries}), encoding='utf-8')
    temporary.replace(manifest)
    return frames, len(entries)
