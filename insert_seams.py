#!/usr/bin/env python3
"""
insert_seams.py - automates the manual workflow of generating extra RIFE
frames at each seam and INSERTING them rather than replacing frames.
The video becomes a few frames longer per seam, spreading the motion jump
across several frames for a smoother transition, including genuine content
jumps rather than only interpolation artifacts.

Unlike fix_seams.py, this script does not remove or overwrite original frames.
It inserts new frames between i and i+1 at the detected seams.

Requires rife-ncnn-vulkan (standalone executable):
  https://github.com/nihui/rife-ncnn-vulkan/releases

Usage:
  python3 insert_seams.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe

  --factor 4   (default) adds 3 frames per seam, matching the manual 4x approach.
               --factor 2 adds one frame for a subtler effect.
               --factor 8 adds seven frames and stretches the transition further.

  --frames 95,119,143,167   supplies seam indices manually instead of detecting
               them (index BEFORE the jump, as reported by find_seams.py).

Audio is stretched uniformly by default (--stretch-audio) to match the longer
video. Approximately regular seam spacing keeps it approximately synchronized.
--no-stretch-audio leaves the original audio unchanged, so it may end earlier.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from seam_utils import find_jumps, detect_jumps, add_detection_options
from seam_utils import (positive_int, positive_float, frame_indices, validate_input,
                        validate_frames, exclude_scene_cuts)


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Input video")
    ap.add_argument("output", help="Output video (repaired, longer than the original)")
    ap.add_argument("--threshold", type=positive_float, default=3.0)
    ap.add_argument("--include-scene-cuts", action="store_true")
    ap.add_argument("--frames", type=frame_indices, default=None,
                     help="Comma-separated seam frame indices (override automatic detection)")
    ap.add_argument("--factor", type=positive_int, default=4,
                     help="Interpolation factor per seam: factor-1 new frames "
                          "are inserted between i and i+1 (default: 4 -> 3 new frames)")
    ap.add_argument("--rife-bin", type=str, required=True)
    ap.add_argument("--rife-model", type=str, default=None)
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--stretch-audio", dest="stretch_audio", action="store_true", default=True)
    ap.add_argument("--no-stretch-audio", dest="stretch_audio", action="store_false")
    ap.add_argument("--keep-frames", action="store_true")
    add_detection_options(ap)
    args = ap.parse_args()
    if args.factor < 2:
        ap.error('--factor must be at least 2.')
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
        seam_frames = find_jumps(scores, args.threshold, min_relative_jump=args.min_relative_jump, recover_periodic=not args.no_periodic_recovery)
        if not args.include_scene_cuts:
            seam_frames = exclude_scene_cuts(args.input, seam_frames)
        print(f"{len(seam_frames)} seams found: {seam_frames}")

    if not seam_frames:
        print("No seams found -> nothing to do.")
        return

    has_audio = ffprobe_has_audio(args.input)
    orig_duration = ffprobe_duration(args.input)

    tmp_ctx = tempfile.TemporaryDirectory()
    work_dir = Path(tmp_ctx.name) if not args.keep_frames else Path(tempfile.mkdtemp(prefix="insert_seams_frames_", dir="."))
    frames_dir = work_dir / "frames"
    new_dir = work_dir / "frames_new"
    frames_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting all frames losslessly to {frames_dir} ...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", args.input, "-vsync", "0", str(frames_dir / "frame_%06d.png")],
        check=True, capture_output=True,
    )
    n_frames = len(list(frames_dir.glob("frame_*.png")))
    validate_frames(seam_frames, n_frames)
    print(f"{n_frames} frames extracted.")

    def orig_path(idx0):
        idx0 = max(0, min(idx0, n_frames - 1))
        return frames_dir / f"frame_{idx0 + 1:06d}.png"

    seam_set = set(seam_frames)
    out_idx = 1
    total_inserted = 0

    print(f"Building the new sequence (factor {args.factor}, "
          f"+{args.factor - 1} frames per seam) ...")
    for i in range(n_frames):
        shutil.copy(orig_path(i), new_dir / f"frame_{out_idx:06d}.png")
        out_idx += 1
        if i in seam_set and i + 1 < n_frames:
            a_path, b_path = orig_path(i), orig_path(i + 1)
            for k in range(1, args.factor):
                t = k / args.factor
                out_p = new_dir / f"frame_{out_idx:06d}.png"
                print(f"  + Frame after original frame {i + 1:06d}: RIFE(t={t:.3f})")
                run_rife(a_path, b_path, out_p, t, args.rife_bin, args.rife_model)
                out_idx += 1
                total_inserted += 1

    new_total = out_idx - 1
    new_duration = new_total / fps
    print(f"\n{total_inserted} frames inserted. "
          f"{n_frames} -> {new_total} Frames "
          f"({orig_duration:.2f}s -> {new_duration:.2f}s at {fps} fps)")

    print(f"Final encode (CRF {args.crf}) ...")
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(new_dir / "frame_%06d.png")]
    if has_audio:
        if args.stretch_audio:
            tempo = orig_duration / new_duration  # <1 => atempo stretches (slows down) the audio
            print(f"Stretching audio with tempo factor {tempo:.4f} to maintain approximate synchronization.")
            cmd += ["-i", args.input, "-filter:a", f"atempo={tempo:.6f}",
                    "-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-i", args.input, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p", args.output]
    subprocess.run(cmd, check=True)

    if not args.keep_frames:
        tmp_ctx.cleanup()

    print(f"\nDone: {args.output}")


if __name__ == "__main__":
    main()
