#!/usr/bin/env python3
"""
find_seams.py - detects periodic seams (chunk-boundary jumps) in AI-generated
videos such as Seedance. These are motion discontinuities associated with
generation chunks, rather than duplicate frames.

Approach:
  - Measure motion for each frame pair (i, i+1) using mean pixel difference
    after a light blur to reduce ordinary noise.
  - Identify unusually large values relative to local motion.
  - Examine candidate spacing for recurring patterns, such as 16 or 24 frames.

Usage:
  python3 find_seams.py input.mp4
  python3 find_seams.py input.mp4 --threshold 2.5 --min-period 4

Output:
  - Frame indices and timestamps with unusually large jumps.
  - Estimated periodicity, if detected.
  - Raw scores in score_per_frame.csv for manual inspection, for example
    in Excel/Numbers when the heuristic needs checking.
"""

import argparse
import csv
import sys
from collections import Counter

import cv2
import numpy as np
from seam_utils import find_jumps, detect_jumps, add_detection_options
from seam_utils import positive_float, positive_int, exclude_scene_cuts


def compute_motion_scores(path, resize_width=320):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open video: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    scores = []

    prev_gray = None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        h, w = frame.shape[:2]
        scale = resize_width / w
        small = cv2.resize(frame, (resize_width, int(h * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray).astype(np.float32)
            scores.append(float(diff.mean()))

        prev_gray = gray
        idx += 1

    cap.release()
    return np.array(scores), fps


def cluster_period(jump_indices, min_period=3):
    if len(jump_indices) < 2:
        return None, []
    diffs = [b - a for a, b in zip(jump_indices, jump_indices[1:]) if b - a >= min_period]
    if not diffs:
        return None, diffs
    counter = Counter(diffs)
    most_common_period, count = counter.most_common(1)[0]
    confidence = count / len(diffs)
    if count < 3 or confidence < 0.6:
        return None, diffs
    return most_common_period, diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="Video path (e.g. seedance_output.mp4)")
    ap.add_argument("--threshold", type=positive_float, default=3.0,
                     help="Robust Z-score threshold for jumps (default: 3.0; lower is more sensitive)")
    ap.add_argument("--include-scene-cuts", action="store_true", help="Disable the scene-cut filter")
    ap.add_argument("--min-period", type=positive_int, default=3,
                     help="Minimum frame interval counted as a period")
    add_detection_options(ap)
    args = ap.parse_args()

    print(f"Analyzing {args.video} ...")
    scores, fps = compute_motion_scores(args.video)
    print(f"{len(scores)} frame transitions analyzed, fps={fps:.2f}")

    with open("score_per_frame.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "to_next_frame_score", "timestamp_s"])
        for i, s in enumerate(scores):
            w.writerow([i, round(float(s), 4), round(i / fps, 3)])
    print("Raw scores saved to score_per_frame.csv")

    jumps, detection = detect_jumps(scores, args.threshold,
                                   min_relative_jump=args.min_relative_jump,
                                   recover_periodic=not args.no_periodic_recovery)
    if not args.include_scene_cuts:
        jumps = exclude_scene_cuts(args.video, jumps)
    if not jumps:
        print("\nNo suspicious jumps found. Try lowering --threshold "
              "(e.g. 2.0), or inspect score_per_frame.csv manually - "
              "look for values that periodically exceed the surrounding scores.")
        return

    print(f"\n{len(jumps)} suspicious seams found (transition from frame i -> i+1):")
    for i in jumps:
        print(f"  Frame {i:5d} -> {i+1:5d}   (t={i/fps:6.2f}s)   score={scores[i]:.2f}")

    recovered = [i for i in detection['recovered'] if i in jumps]
    if recovered:
        print(f'Recovered periodic peaks: {recovered}')
    # Confidence must come from independently detected peaks, not recovered ones.
    period, diffs = cluster_period([i for i in detection['strong'] if i in jumps], args.min_period)
    if period:
        print(f"\nLikely periodicity: every ~{period} frames "
              f"(~{period/fps:.2f}s at {fps:.1f} fps)")
        confidence = diffs.count(period) / len(diffs)
        print(f'Matching intervals: {confidence:.0%} '
              f'({diffs.count(period)}/{len(diffs)}). This does not prove a model window size.')
    else:
        print("\nNo clear periodic pattern detected - jumps may also come "
              "from the scene itself (fast motion), rather than the model.")


if __name__ == "__main__":
    main()
