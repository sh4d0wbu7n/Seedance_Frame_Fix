#!/usr/bin/env python3
"""
insert_best_frame.py — automatisiert das manuelle "richtigen Frame raussuchen
und einfügen". An jeder Sprungstelle werden mehrere RIFE-Kandidatenframes an
verschiedenen Zeitpunkten zwischen Frame i und i+1 erzeugt (Standard: 7
Kandidaten, wie bei Faktor 8). Für jeden Kandidaten wird gemessen, wie groß
der verbleibende Bewegungssprung auf beiden Seiten wäre (i -> Kandidat und
Kandidat -> i+1). Gewählt wird der Kandidat, bei dem beide Seiten möglichst
ausgeglichen sind (kein großer Rest-Sprung mehr übrig) - das ist der Frame,
der den ursprünglichen Sprung am saubersten "in der Mitte trifft".

Nur EIN Frame pro Sprungstelle wird eingefügt (nicht mehrere) - das Video
wird dadurch nur um die Anzahl der Sprungstellen länger (z.B. +22 Frames
bei 22 Sprungstellen, keine ~66 wie bei Faktor 4 mit 3 Frames/Stelle).

WICHTIG: braucht rife-ncnn-vulkan:
  https://github.com/nihui/rife-ncnn-vulkan/releases

Nutzung:
  python3 insert_best_frame.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe

  --candidates 7   Anzahl der Kandidaten-Zeitpunkte zwischen Frame i und i+1
                   (mehr = feinere Auswahl, aber mehr RIFE-Aufrufe pro Stelle)
  --frames 95,119,...   Sprungstellen manuell vorgeben statt Auto-Erkennung

Zwischendateien: alle extrahierten Frames, generierten Kandidaten und die neu
zusammengesetzte Sequenz landen in einem Projektordner (Standard:
<output>_work/ neben der Ausgabedatei) und werden NICHT automatisch gelöscht.
So kannst du dir einzelne Kandidaten nachträglich ansehen oder von Hand
nachbessern. Mit --workdir lässt sich der Ort explizit vorgeben, mit --clean
wird ein vorher vorhandener Workdir-Inhalt vor dem Lauf geleert.
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
        sys.exit(f"Konnte Video nicht öffnen: {path}")
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
        sys.exit(f"RIFE-Aufruf fehlgeschlagen:\n{' '.join(cmd)}\n{result.stderr}")


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
    """Erzeugt Kandidaten bei mehreren t-Werten und wählt den mit dem am
    besten ausgeglichenen Split (min. des größeren der beiden Rest-Sprünge)."""
    if candidates < 1:
        raise ValueError('Mindestens ein Kandidat erforderlich.')
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
    ap.add_argument("input", help="Eingabevideo")
    ap.add_argument("output", help="Ausgabevideo (ein Frame länger pro Sprungstelle)")
    ap.add_argument("--threshold", type=positive_float, default=3.0)
    ap.add_argument("--include-scene-cuts", action="store_true", help="Szenenschnitt-Filter deaktivieren")
    ap.add_argument("--frames", type=frame_indices, default=None,
                     help="Kommagetrennte Liste von Sprung-Frame-Indizes (überschreibt Auto-Erkennung)")
    ap.add_argument("--candidates", type=positive_int, default=7,
                     help="Anzahl Kandidaten-Zeitpunkte pro Sprungstelle (default 7, wie Faktor 8)")
    ap.add_argument("--rife-bin", type=str, required=True)
    ap.add_argument("--rife-model", type=str, default=None)
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--stretch-audio", dest="stretch_audio", action="store_true", default=True)
    ap.add_argument("--no-stretch-audio", dest="stretch_audio", action="store_false")
    ap.add_argument("--workdir", type=str, default=None,
                     help="Projektordner für Zwischendateien (Frames, Kandidaten). "
                          "Default: <output>_work/ neben der Ausgabedatei. Wird NICHT "
                          "automatisch gelöscht.")
    ap.add_argument("--clean", action="store_true",
                     help="Workdir vor dem Lauf leeren (z.B. wenn sich die Sprungstellen "
                          "seit dem letzten Lauf geändert haben)")
    add_detection_options(ap)
    args = ap.parse_args()
    validate_input(args, ap)

    if not shutil.which(args.rife_bin) and not Path(args.rife_bin).exists():
        sys.exit(f"rife-ncnn-vulkan nicht gefunden unter: {args.rife_bin}\n"
                  f"Lade es von https://github.com/nihui/rife-ncnn-vulkan/releases")

    if args.frames is not None:
        seam_frames = args.frames
        cap = cv2.VideoCapture(args.input)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.release()
    else:
        print("Erkenne Sprungstellen ...")
        scores, fps = compute_motion_scores(args.input)
        seam_frames, detection = detect_jumps(scores, args.threshold,
                                             min_relative_jump=args.min_relative_jump,
                                             recover_periodic=not args.no_periodic_recovery)
        if detection['recovered']:
            print(f'Periodische Bewegungsspitzen ergaenzt: {detection["recovered"]}')
        if not args.include_scene_cuts:
            seam_frames = exclude_scene_cuts(args.input, seam_frames)
        print(f"{len(seam_frames)} Sprungstellen gefunden: {seam_frames}")

    if not seam_frames:
        print("Keine Sprungstellen -> nichts zu tun.")
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
    print(f"{n_frames} Frames extrahiert.")

    def orig_path(idx0):
        idx0 = max(0, min(idx0, n_frames - 1))
        return frames_dir / f"frame_{idx0 + 1:06d}.png"

    seam_set = set(seam_frames)
    out_idx = 1
    seam_report = []

    print(f"Suche pro Sprungstelle den besten von {args.candidates} Kandidaten-Frames ...")
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
            print(f"  Sprung {i + 1:06d}->{i + 2:06d}: bester t={t:.3f} "
                  f"(gap vorher={total_gap:.2f}, links={left:.2f}, rechts={right:.2f})")
            out_p = new_dir / f"frame_{out_idx:06d}.png"
            if not cv2.imwrite(str(out_p), cand_img):
                sys.exit(f'Frame konnte nicht gespeichert werden: {out_p}')
            out_idx += 1

    new_total = out_idx - 1
    new_duration = new_total / fps
    print(f"\n{n_frames} -> {new_total} Frames "
          f"({orig_duration:.2f}s -> {new_duration:.2f}s bei {fps} fps)")

    print(f"Finaler Encode (CRF {args.crf}) ...")
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(new_dir / "frame_%06d.png")]
    if has_audio:
        if args.stretch_audio:
            tempo = orig_duration / new_duration
            print(f"Ton wird um Faktor {tempo:.4f} gestreckt, um synchron zu bleiben.")
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
    print(f'Messbericht: {report_path}')

    print(f"\nFertig: {args.output}")
    print(f"Zwischendateien liegen weiterhin in {work_dir.resolve()} "
          f"(Kandidaten pro Sprungstelle in {cand_dir}/, finale Sequenz in {new_dir}/).")


if __name__ == "__main__":
    main()
