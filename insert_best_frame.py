#!/usr/bin/env python3
"""
insert_best_frame.py - automates selecting and inserting the best intermediate
frame. At each seam, RIFE generates candidates at different timestamps between
frames i and i+1 (default: seven candidates, equivalent to factor 8).
Each candidate is scored by the remaining motion jump on both sides
(i -> candidate and candidate -> i+1). The candidate with the most balanced
split minimizes the larger residual jump.

Only ONE frame is inserted per seam, increasing duration by the seam count
in frames (for example, 22 extra frames for 22 seams, not the roughly 66 frames
added by factor 4 with three insertions per seam).

Requires rife-ncnn-vulkan:
  https://github.com/nihui/rife-ncnn-vulkan/releases

Usage:
  python3 insert_best_frame.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe

  --candidates 7   Number of candidate timestamps between i and i+1.
                   More candidates provide finer selection but more RIFE calls.
  --frames 95,119,...   Supply seams manually instead of automatic detection.

Intermediate files (extracted frames, candidates, and the assembled sequence)
remain in a working directory, defaulting to <output>_work/ next to the output.
They are NOT automatically deleted, allowing later inspection or manual
refinement. --workdir selects a directory; --clean refreshes managed working
files before a run.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from seam_utils import find_jumps, detect_jumps, add_detection_options
from seam_utils import (positive_int, positive_float, frame_indices, validate_input,
                        validate_frames, exclude_scene_cuts, prepare_workdir,
                        reset_owned_dir, cached_frames)


def compute_motion_scores(path, resize_width=320):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    scores = []
    prev_gray = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (resize_width, int(h * resize_width / w)))
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        if prev_gray is not None:
            scores.append(float(cv2.absdiff(gray, prev_gray).astype(np.float32).mean()))
        prev_gray = gray
    cap.release()
    return np.array(scores), fps


def frame_diff_score(img_a, img_b, resize_width=320):
    h, w = img_a.shape[:2]
    a = cv2.resize(img_a, (resize_width, int(h * resize_width / w)))
    b = cv2.resize(img_b, (resize_width, int(h * resize_width / w)))
    ga = cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    gb = cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    return float(cv2.absdiff(ga, gb).astype(np.float32).mean())


def run_rife(a_path, b_path, out_path, t, rife_bin, rife_model):
    cmd = [rife_bin, "-0", str(a_path), "-1", str(b_path), "-s", str(t), "-o", str(out_path)]
    if rife_model:
        cmd += ["-m", rife_model]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_path.exists():
        sys.exit(f"RIFE invocation failed:\n{' '.join(cmd)}\n{result.stderr}")


def ffprobe_has_audio(path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
           "stream=index", "-of", "csv=p=0", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return bool(result.stdout.strip())


def ffprobe_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "csv=p=0", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def find_best_candidate(a_path, b_path, candidates, rife_bin, rife_model, work_dir):
    """Generate candidates at several timestamps and select the most balanced
    split by minimizing the larger of the two residual jumps."""
    if candidates < 1:
        raise ValueError('At least one candidate is required.')
    work_dir.mkdir(parents=True, exist_ok=True)
    img_a = cv2.imread(str(a_path))
    img_b = cv2.imread(str(b_path))
    total_gap = frame_diff_score(img_a, img_b)

    best = None  # (worst_side_score, t, image, path)
    for k in range(1, candidates + 1):
        t = k / (candidates + 1)
        cand_path = work_dir / f"cand_{k}.png"
        run_rife(a_path, b_path, cand_path, t, rife_bin, rife_model)
        cand_img = cv2.imread(str(cand_path))

        left = frame_diff_score(img_a, cand_img)
        right = frame_diff_score(cand_img, img_b)
        worst = max(left, right)

        if best is None or worst < best[0]:
            best = (worst, t, cand_img.copy(), left, right)

    return best  # (worst_side_score, chosen_t, image, left_score, right_score), total_gap


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Input video")
    ap.add_argument("output", help="Output video (one extra frame per seam)")
    ap.add_argument("--threshold", type=positive_float, default=3.0)
    ap.add_argument("--include-scene-cuts", action="store_true", help="Disable the scene-cut filter")
    ap.add_argument("--frames", type=frame_indices, default=None,
                     help="Comma-separated seam frame indices (override automatic detection)")
    ap.add_argument("--candidates", type=positive_int, default=7,
                     help="Candidate timestamps per seam (default: 7, as with factor 8)")
    ap.add_argument("--rife-bin", type=str, required=True)
    ap.add_argument("--rife-model", type=str, default=None)
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--stretch-audio", dest="stretch_audio", action="store_true", default=True)
    ap.add_argument("--no-stretch-audio", dest="stretch_audio", action="store_false")
    ap.add_argument("--workdir", type=str, default=None,
                     help="Working directory for intermediate frames and candidates. "
                          "Default: <output>_work/ next to the output. NOT "
                          "automatically deleted.")
    ap.add_argument("--clean", action="store_true",
                     help="Refresh managed working files before running (e.g. if seams "
                          "have changed since the previous run)")
    add_detection_options(ap)
    args = ap.parse_args()
    validate_input(args, ap)

    if not shutil.which(args.rife_bin) and not Path(args.rife_bin).exists():
        sys.exit(f"rife-ncnn-vulkan not found at: {args.rife_bin}\n"
                  f"Download it from https://github.com/nihui/rife-ncnn-vulkan/releases")

    if args.frames is not None:
        seam_frames = args.frames
        cap = cv2.VideoCapture(args.input)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.release()
    else:
        print("Detecting seams ...")
        scores, fps = compute_motion_scores(args.input)
        seam_frames, detection = detect_jumps(scores, args.threshold,
                                             min_relative_jump=args.min_relative_jump,
                                             recover_periodic=not args.no_periodic_recovery)
        if detection['recovered']:
            print(f'Recovered periodic motion peaks: {detection["recovered"]}')
        if not args.include_scene_cuts:
            seam_frames = exclude_scene_cuts(args.input, seam_frames)
        print(f"{len(seam_frames)} seams found: {seam_frames}")

    if not seam_frames:
        print("No seams found -> nothing to do.")
        return

    has_audio = ffprobe_has_audio(args.input)
    orig_duration = ffprobe_duration(args.input)

    if args.workdir:
        work_dir = Path(args.workdir)
    else:
        out_path = Path(args.output)
        work_dir = out_path.parent / f"{out_path.stem}_work"

    try:
        work_dir = prepare_workdir(work_dir, args.input, args.output)
        frames_dir, n_frames = cached_frames(work_dir, args.input, args.clean)
        validate_frames(seam_frames, n_frames)
        new_dir = reset_owned_dir(work_dir, 'frames_new')
        cand_dir = reset_owned_dir(work_dir, 'candidates')
    except ValueError as exc:
        ap.error(str(exc))
    print(f"{n_frames} frames extracted.")

    def orig_path(idx0):
        idx0 = max(0, min(idx0, n_frames - 1))
        return frames_dir / f"frame_{idx0 + 1:06d}.png"

    seam_set = set(seam_frames)
    out_idx = 1
    seam_report = []

    print(f"Selecting the best of {args.candidates} candidate frames per seam ...")
    for i in range(n_frames):
        shutil.copy(orig_path(i), new_dir / f"frame_{out_idx:06d}.png")
        out_idx += 1
        if i in seam_set:
            a_path, b_path = orig_path(i), orig_path(i + 1)
            worst, t, cand_img, left, right = find_best_candidate(
                a_path, b_path, args.candidates, args.rife_bin, args.rife_model,
                cand_dir / f'seam_{i:06d}'
            )
            total_gap = frame_diff_score(cv2.imread(str(a_path)), cv2.imread(str(b_path)))
            seam_report.append({'frame_index': i, 'time_seconds': (i + 1) / fps,
                                'chosen_t': t, 'gap_before': total_gap,
                                'gap_left': left, 'gap_right': right,
                                'reduction_fraction': 1 - worst / max(total_gap, 1e-6)})
            print(f"  Seam {i + 1:06d}->{i + 2:06d}: best t={t:.3f} "
                  f"(gap before={total_gap:.2f}, left={left:.2f}, right={right:.2f})")
            out_p = new_dir / f"frame_{out_idx:06d}.png"
            if not cv2.imwrite(str(out_p), cand_img):
                sys.exit(f'Could not save frame: {out_p}')
            out_idx += 1

    new_total = out_idx - 1
    new_duration = new_total / fps
    print(f"\n{n_frames} -> {new_total} Frames "
          f"({orig_duration:.2f}s -> {new_duration:.2f}s at {fps} fps)")

    print(f"Final encode (CRF {args.crf}) ...")
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(new_dir / "frame_%06d.png")]
    if has_audio:
        if args.stretch_audio:
            tempo = orig_duration / new_duration
            print(f"Stretching audio with tempo factor {tempo:.4f} to maintain approximate synchronization.")
            cmd += ["-i", args.input, "-filter:a", f"atempo={tempo:.6f}",
                    "-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-i", args.input, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p", args.output]
    subprocess.run(cmd, check=True)

    report = {'original_frames': n_frames, 'output_frames': new_total, 'fps': fps,
              'candidate_count': args.candidates,
              'detection': {'manual_frames': args.frames,
                            'threshold': args.threshold,
                            'min_relative_jump': args.min_relative_jump,
                            'periodic_recovery': not args.no_periodic_recovery},
              'metric': 'Mean absolute blurred grayscale difference at 320px; not perceptual quality.',
              'seams': seam_report}
    report_path = work_dir / 'repair_report.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Measurement report: {report_path}')

    print(f"\nDone: {args.output}")
    print(f"Intermediate files remain in {work_dir.resolve()} "
          f"(candidates per seam in {cand_dir}/, final sequence in {new_dir}/).")


if __name__ == "__main__":
    main()
