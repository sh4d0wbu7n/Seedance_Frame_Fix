#!/usr/bin/env python3
"""
fix_seams.py — repariert die periodischen Chunk-Sprungstellen, die find_seams.py
gefunden hat. Es werden NUR die Frames direkt an jeder Sprungstelle ersetzt,
durch echte, KI-basierte Zwischenbilder (RIFE, via rife-ncnn-vulkan) zwischen
dem letzten sauberen Frame davor und dem ersten sauberen danach.

Qualitäts-Pipeline (wichtig!):
  Video -> verlustfreie PNG-Extraktion (ffmpeg) -> nur die betroffenen PNGs
  werden durch RIFE-Output ersetzt -> EIN einziger finaler Encode (ffmpeg,
  hohe Qualität). Alle unberührten Frames durchlaufen dabei nur die normale
  Kompression, die auch ein direkter Reencode hätte - keine doppelte
  verlustbehaftete Zwischenkompression, die den Gesamteindruck weichzeichnet.

WICHTIG: braucht rife-ncnn-vulkan (fertige .exe/binary, kein Python-Paket):
  https://github.com/nihui/rife-ncnn-vulkan/releases
Entpacken und Pfad zur .exe + Modellordner unten angeben (--rife-bin, --rife-model).

Nutzung:
  1. Erst find_seams.py laufen lassen (optional, nur zur Kontrolle)
  2. Dann:
       python3 fix_seams.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe
     Das Script erkennt die Sprungstellen selbst (gleiche Logik wie find_seams.py)
     und repariert automatisch alle gefundenen Stellen.

  Optional gezielt nur bestimmte Frames reparieren:
       python3 fix_seams.py input.mp4 output.mp4 --frames 95,119,143,167 --rife-bin ...

  --crf steuert die finale Qualität (niedriger = besser/größer, default 14).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


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


def find_jumps(scores, threshold_sigma, window=15):
    n = len(scores)
    jumps = []
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        local = np.delete(scores[lo:hi], min(i, half) if i - lo < half else half)
        if len(local) < 5:
            continue
        med = np.median(local)
        mad = np.median(np.abs(local - med)) + 1e-6
        if (scores[i] - med) / (mad * 1.4826) > threshold_sigma:
            jumps.append(i)
    return jumps


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Eingabevideo")
    ap.add_argument("output", help="Ausgabevideo (repariert)")
    ap.add_argument("--threshold", type=float, default=3.0)
    ap.add_argument("--frames", type=str, default=None,
                     help="Kommagetrennte Liste von Sprung-Frame-Indizes (überschreibt Auto-Erkennung)")
    ap.add_argument("--pad", type=int, default=1,
                     help="Wie viele Frames auf jeder Seite als 'sauber' gelten, "
                          "bevor die Interpolationsbasis genommen wird (default 1)")
    ap.add_argument("--rife-bin", type=str, required=True,
                     help="Pfad zur rife-ncnn-vulkan(.exe) aus dem Release-Zip")
    ap.add_argument("--rife-model", type=str, default=None,
                     help="Pfad zum Modellordner, z.B. rife-ncnn-vulkan/rife-v4.6")
    ap.add_argument("--crf", type=int, default=14,
                     help="x264 CRF fürs finale Encoding, niedriger = bessere Qualität (default 14)")
    ap.add_argument("--keep-frames", action="store_true",
                     help="Temp-Ordner mit den PNG-Frames nicht löschen (zum Nachschauen)")
    args = ap.parse_args()

    if not shutil.which(args.rife_bin) and not Path(args.rife_bin).exists():
        sys.exit(f"rife-ncnn-vulkan nicht gefunden unter: {args.rife_bin}\n"
                  f"Lade es von https://github.com/nihui/rife-ncnn-vulkan/releases")

    if args.frames:
        seam_frames = sorted(set(int(x) for x in args.frames.split(",")))
        cap = cv2.VideoCapture(args.input)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.release()
    else:
        print("Erkenne Sprungstellen ...")
        scores, fps = compute_motion_scores(args.input)
        seam_frames = find_jumps(scores, args.threshold)
        print(f"{len(seam_frames)} Sprungstellen gefunden: {seam_frames}")

    if not seam_frames:
        print("Keine Sprungstellen -> nichts zu tun.")
        return

    # Für jede Sprungstelle i (Übergang i -> i+1) werden Frame i und i+1 ersetzt
    # durch Interpolation zwischen Frame (i - pad) und Frame (i + 1 + pad).
    bad_frames = {}  # 0-based frame_index -> (a_idx, b_idx, t)
    for i in seam_frames:
        a_idx = i - args.pad
        b_idx = i + 1 + args.pad
        bad_frames[i] = (a_idx, b_idx, 1 / 3)
        bad_frames[i + 1] = (a_idx, b_idx, 2 / 3)

    has_audio = ffprobe_has_audio(args.input)

    tmp_ctx = tempfile.TemporaryDirectory()
    work_dir = Path(tmp_ctx.name) if not args.keep_frames else Path("fix_seams_frames")
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extrahiere alle Frames verlustfrei nach {frames_dir} ...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", args.input, "-vsync", "0", str(frames_dir / "frame_%06d.png")],
        check=True, capture_output=True,
    )
    n_frames = len(list(frames_dir.glob("frame_*.png")))
    print(f"{n_frames} Frames extrahiert.")

    def frame_path(idx0):  # 0-based -> ffmpeg's 1-based filename
        idx0 = max(0, min(idx0, n_frames - 1))
        return frames_dir / f"frame_{idx0 + 1:06d}.png"

    print(f"Ersetze {len(bad_frames)} Frames per RIFE ...")
    for idx, (a_idx, b_idx, t) in bad_frames.items():
        if idx < 0 or idx >= n_frames:
            continue
        out_p = frame_path(idx)
        print(f"  Frame {idx + 1:06d}.png <- RIFE({a_idx + 1:06d}, {b_idx + 1:06d}, t={t:.2f})")
        run_rife(frame_path(a_idx), frame_path(b_idx), out_p, t, args.rife_bin, args.rife_model)

    print(f"Finaler Encode (CRF {args.crf}) ...")
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%06d.png")]
    if has_audio:
        cmd += ["-i", args.input, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p", args.output]
    subprocess.run(cmd, check=True)

    if not args.keep_frames:
        tmp_ctx.cleanup()

    print(f"\nFertig: {args.output}")


if __name__ == "__main__":
    main()
