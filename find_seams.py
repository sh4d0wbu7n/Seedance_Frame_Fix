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
from seam_utils import find_jumps, detect_jumps, add_detection_options
from seam_utils import positive_float, positive_int, exclude_scene_cuts


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
    ap.add_argument("video", help="Pfad zum Video (z.B. seedance_output.mp4)")
    ap.add_argument("--threshold", type=positive_float, default=3.0,
                     help="Robuster z-score-Schwellwert für 'Sprung' (default 3.0, kleiner = empfindlicher)")
    ap.add_argument("--include-scene-cuts", action="store_true", help="Szenenschnitt-Filter deaktivieren")
    ap.add_argument("--min-period", type=positive_int, default=3,
                     help="Minimaler Frame-Abstand, der als Periode gezählt wird")
    add_detection_options(ap)
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

    jumps, detection = detect_jumps(scores, args.threshold,
                                   min_relative_jump=args.min_relative_jump,
                                   recover_periodic=not args.no_periodic_recovery)
    if not args.include_scene_cuts:
        jumps = exclude_scene_cuts(args.video, jumps)
    if not jumps:
        print("\nKeine auffälligen Sprünge gefunden. Versuch --threshold kleiner "
              "(z.B. 2.0), oder schau dir score_per_frame.csv manuell an — "
              "such nach Werten, die periodisch über dem Rest liegen.")
        return

    print(f"\n{len(jumps)} auffällige Sprungstellen gefunden (Übergang Frame i -> i+1):")
    for i in jumps:
        print(f"  Frame {i:5d} -> {i+1:5d}   (t={i/fps:6.2f}s)   score={scores[i]:.2f}")

    recovered = [i for i in detection['recovered'] if i in jumps]
    if recovered:
        print(f'Periodisch ergaenzte Spitzen: {recovered}')
    # Confidence must come from independently detected peaks, not recovered ones.
    period, diffs = cluster_period([i for i in detection['strong'] if i in jumps], args.min_period)
    if period:
        print(f"\nWahrscheinliche Periodizität: alle ~{period} Frames "
              f"(~{period/fps:.2f}s bei {fps:.1f} fps)")
        confidence = diffs.count(period) / len(diffs)
        print(f'Uebereinstimmung der Abstaende: {confidence:.0%} '
              f'({diffs.count(period)}/{len(diffs)}). Kein Beweis fuer eine Modell-Fenstergroesse.')
    else:
        print("\nKein klar periodisches Muster erkannt — die Sprünge könnten "
              "auch von der Szene selbst kommen (schnelle Bewegung), nicht vom Modell.")


if __name__ == "__main__":
    main()
