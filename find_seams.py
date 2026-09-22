#!/usr/bin/env python3
"""
find_seams.py — findet periodische "Sprungstellen" (chunk boundary jumps) in
KI-generierten Videos (z.B. Seedance), die NICHT von doppelten Frames kommen,
sondern von den internen Generierungs-Chunks des Modells.

Idee:
  - Für jedes Frame-Paar (i, i+1) wird die Bewegung gemessen (mittlere
    Pixel-Differenz nach leichtem Blur, robust gegen normales Rauschen).
  - Werte, die deutlich über dem lokalen Mittelwert liegen, sind Kandidaten
    für einen "Sprung".
  - Der Abstand zwischen den Kandidaten wird geclustert, um ein
    wiederkehrendes Muster (z.B. alle 16, alle 24 Frames) zu erkennen.

Nutzung:
  python3 find_seams.py input.mp4
  python3 find_seams.py input.mp4 --threshold 2.5 --min-period 4

Output:
  - Liste der Frame-Indizes / Timestamps mit ungewöhnlich großem Sprung
  - Geschätzte Periodizität (z.B. "alle ~24 Frames"), falls erkennbar
  - CSV mit allen Rohwerten (score_per_frame.csv) zum manuellen Nachschauen
    z.B. in Excel/Numbers, falls die Heuristik daneben liegt
"""

import argparse
import csv
import sys
from collections import Counter

import cv2
import numpy as np


def compute_motion_scores(path, resize_width=320):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Konnte Video nicht öffnen: {path}")

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


def find_jumps(scores, threshold_sigma, window=15):
    """Findet Frames, deren Bewegungs-Score deutlich über dem lokalen
    Median liegt (robust gegen langsam wechselnde Szenen)."""
    n = len(scores)
    jumps = []
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        local = np.delete(scores[lo:hi], min(i, half) if i - lo < half else half)
        if len(local) < 5:
            continue
        med = np.median(local)
        mad = np.median(np.abs(local - med)) + 1e-6  # median absolute deviation
        z = (scores[i] - med) / (mad * 1.4826)  # ~ robust z-score
        if z > threshold_sigma:
            jumps.append(i)
    return jumps


def cluster_period(jump_indices, min_period=3):
    if len(jump_indices) < 2:
        return None, []
    diffs = [b - a for a, b in zip(jump_indices, jump_indices[1:]) if b - a >= min_period]
    if not diffs:
        return None, diffs
    counter = Counter(diffs)
    most_common_period, count = counter.most_common(1)[0]
    return most_common_period, diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="Pfad zum Video (z.B. seedance_output.mp4)")
    ap.add_argument("--threshold", type=float, default=3.0,
                     help="Robuster z-score-Schwellwert für 'Sprung' (default 3.0, kleiner = empfindlicher)")
    ap.add_argument("--min-period", type=int, default=3,
                     help="Minimaler Frame-Abstand, der als Periode gezählt wird")
    args = ap.parse_args()

    print(f"Analysiere {args.video} ...")
    scores, fps = compute_motion_scores(args.video)
    print(f"{len(scores)} Frame-Übergänge ausgewertet, fps={fps:.2f}")

    with open("score_per_frame.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "to_next_frame_score", "timestamp_s"])
        for i, s in enumerate(scores):
            w.writerow([i, round(float(s), 4), round(i / fps, 3)])
    print("Rohwerte gespeichert in score_per_frame.csv")

    jumps = find_jumps(scores, args.threshold)
    if not jumps:
        print("\nKeine auffälligen Sprünge gefunden. Versuch --threshold kleiner "
              "(z.B. 2.0), oder schau dir score_per_frame.csv manuell an — "
              "such nach Werten, die periodisch über dem Rest liegen.")
        return

    print(f"\n{len(jumps)} auffällige Sprungstellen gefunden (Übergang Frame i -> i+1):")
    for i in jumps:
        print(f"  Frame {i:5d} -> {i+1:5d}   (t={i/fps:6.2f}s)   score={scores[i]:.2f}")

    period, diffs = cluster_period(jumps, args.min_period)
    if period:
        print(f"\nWahrscheinliche Periodizität: alle ~{period} Frames "
              f"(~{period/fps:.2f}s bei {fps:.1f} fps)")
        print("-> passt das zu einer festen Chunk-Länge deines Generators? "
              "Das ist so gut wie sicher die interne Fenstergröße des Modells.")
    else:
        print("\nKein klar periodisches Muster erkannt — die Sprünge könnten "
              "auch von der Szene selbst kommen (schnelle Bewegung), nicht vom Modell.")


if __name__ == "__main__":
    main()
