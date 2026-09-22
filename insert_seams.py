#!/usr/bin/env python3
"""
insert_seams.py — automatisiert genau den manuellen Workflow: an jeder
Sprungstelle werden per RIFE zusätzliche Zwischenframes erzeugt und
EINGEFÜGT (nicht ersetzt). Das Video wird dadurch an jeder Stelle um ein
paar Frames länger, der Sprung verteilt sich über mehrere Frames statt
in einem einzigen abrupten Schnitt zu passieren -> deutlich weicher, auch
bei echten Inhaltssprüngen (nicht nur bei reinen Interpolationsfehlern).

Im Gegensatz zu fix_seams.py wird hier NICHTS aus dem Originalvideo entfernt
oder überschrieben - nur zusätzliche Frames werden zwischen Frame i und
Frame i+1 eingefügt, exakt an den erkannten Sprungstellen.

WICHTIG: braucht rife-ncnn-vulkan (fertige .exe/binary):
  https://github.com/nihui/rife-ncnn-vulkan/releases

Nutzung:
  python3 insert_seams.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe

  --factor 4   (default) fügt 3 neue Frames pro Sprungstelle ein (so wie dein
               manueller 4x-Ansatz). --factor 2 fügt nur 1 Frame ein (subtiler),
               --factor 8 fügt 7 Frames ein (noch sanfter, Sprung wird noch
               stärker gestreckt).

  --frames 95,119,143,167   um die Sprungstellen manuell statt automatisch
               vorzugeben (Frame-Index VOR dem Sprung, wie von find_seams.py
               ausgegeben).

Audio: falls das Video Ton hat, wird er standardmäßig gleichmäßig gestreckt
(--stretch-audio, default an), damit die Gesamtlänge zum längeren Video passt.
Da die Sprungstellen (typischerweise) regelmäßig über das Video verteilt sind,
bleibt der Ton dadurch über das ganze Video hinweg näherungsweise synchron.
Mit --no-stretch-audio bleibt der Ton unverändert (kann am Ende leicht
vorher enden).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from seam_utils import (positive_int, positive_float, frame_indices, validate_input,
                        validate_frames, exclude_scene_cuts)


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


def ffprobe_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "csv=p=0", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Eingabevideo")
    ap.add_argument("output", help="Ausgabevideo (repariert, länger als das Original)")
    ap.add_argument("--threshold", type=positive_float, default=3.0)
    ap.add_argument("--include-scene-cuts", action="store_true")
    ap.add_argument("--frames", type=frame_indices, default=None,
                     help="Kommagetrennte Liste von Sprung-Frame-Indizes (überschreibt Auto-Erkennung)")
    ap.add_argument("--factor", type=positive_int, default=4,
                     help="Interpolationsfaktor an jeder Sprungstelle: factor-1 neue Frames "
                          "werden zwischen Frame i und i+1 eingefügt (default 4 -> 3 neue Frames)")
    ap.add_argument("--rife-bin", type=str, required=True)
    ap.add_argument("--rife-model", type=str, default=None)
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--stretch-audio", dest="stretch_audio", action="store_true", default=True)
    ap.add_argument("--no-stretch-audio", dest="stretch_audio", action="store_false")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()
    if args.factor < 2:
        ap.error('--factor muss mindestens 2 sein.')
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
        seam_frames = find_jumps(scores, args.threshold)
        if not args.include_scene_cuts:
            seam_frames = exclude_scene_cuts(args.input, seam_frames)
        print(f"{len(seam_frames)} Sprungstellen gefunden: {seam_frames}")

    if not seam_frames:
        print("Keine Sprungstellen -> nichts zu tun.")
        return

    has_audio = ffprobe_has_audio(args.input)
    orig_duration = ffprobe_duration(args.input)

    tmp_ctx = tempfile.TemporaryDirectory()
    work_dir = Path(tmp_ctx.name) if not args.keep_frames else Path(tempfile.mkdtemp(prefix="insert_seams_frames_", dir="."))
    frames_dir = work_dir / "frames"
    new_dir = work_dir / "frames_new"
    frames_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extrahiere alle Frames verlustfrei nach {frames_dir} ...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", args.input, "-vsync", "0", str(frames_dir / "frame_%06d.png")],
        check=True, capture_output=True,
    )
    n_frames = len(list(frames_dir.glob("frame_*.png")))
    validate_frames(seam_frames, n_frames)
    print(f"{n_frames} Frames extrahiert.")

    def orig_path(idx0):
        idx0 = max(0, min(idx0, n_frames - 1))
        return frames_dir / f"frame_{idx0 + 1:06d}.png"

    seam_set = set(seam_frames)
    out_idx = 1
    total_inserted = 0

    print(f"Baue neue Sequenz auf (Faktor {args.factor}, "
          f"+{args.factor - 1} Frames pro Sprungstelle) ...")
    for i in range(n_frames):
        shutil.copy(orig_path(i), new_dir / f"frame_{out_idx:06d}.png")
        out_idx += 1
        if i in seam_set and i + 1 < n_frames:
            a_path, b_path = orig_path(i), orig_path(i + 1)
            for k in range(1, args.factor):
                t = k / args.factor
                out_p = new_dir / f"frame_{out_idx:06d}.png"
                print(f"  + Frame nach Original-Frame {i + 1:06d}: RIFE(t={t:.3f})")
                run_rife(a_path, b_path, out_p, t, args.rife_bin, args.rife_model)
                out_idx += 1
                total_inserted += 1

    new_total = out_idx - 1
    new_duration = new_total / fps
    print(f"\n{total_inserted} Frames eingefügt. "
          f"{n_frames} -> {new_total} Frames "
          f"({orig_duration:.2f}s -> {new_duration:.2f}s bei {fps} fps)")

    print(f"Finaler Encode (CRF {args.crf}) ...")
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(new_dir / "frame_%06d.png")]
    if has_audio:
        if args.stretch_audio:
            tempo = orig_duration / new_duration  # <1 => atempo streckt (verlangsamt) den Ton
            print(f"Ton wird um Faktor {tempo:.4f} gestreckt, um synchron zu bleiben.")
            cmd += ["-i", args.input, "-filter:a", f"atempo={tempo:.6f}",
                    "-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-i", args.input, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p", args.output]
    subprocess.run(cmd, check=True)

    if not args.keep_frames:
        tmp_ctx.cleanup()

    print(f"\nFertig: {args.output}")


if __name__ == "__main__":
    main()
