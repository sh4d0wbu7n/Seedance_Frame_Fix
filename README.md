# Seedance Seam Fix

Fixes periodic stutters in AI-generated videos (such as Seedance 2.5) associated
with chunk boundaries in video diffusion generation. These are **not** duplicate
or missing frames: they are small motion discontinuities at regular intervals
(typically about 24 frames / one second in the observed Seedance footage).

The fix detects these transitions, generates the best intermediate frame with
RIFE, and inserts **exactly one frame** per transition. The video becomes one
frame longer per repair, distributing the jump over two smaller motion steps.

## Requirements

- Python 3.9+
- [FFmpeg](https://ffmpeg.org/download.html), available on PATH
- [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan/releases):
  a portable command-line tool using Vulkan on Windows/Linux/macOS.
  No CUDA or PyTorch installation is required.

## Installation

```bash
git clone <this-repository>
cd seedance-seam-fix

python3 -m venv venv
# macOS/Linux:
source venv/bin/activate
# Windows (PowerShell; if execution policy blocks activation, first run
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser):
venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` contains:

```text
opencv-python-headless
numpy
```

Download and extract [RIFE](https://github.com/nihui/rife-ncnn-vulkan/releases),
for example into `./rife-ncnn-vulkan/`. The ZIP includes the executable
(`rife-ncnn-vulkan` or `.exe`) and model directories such as `rife-v4.6`.
It is portable and requires no further installation.

## Usage

### Windows desktop launcher

Double-click `Seedance Frame Fix.cmd` on the desktop and select a video,
or drag a video onto the launcher. The result is saved next to the input as
`<name>_fixed.mp4`. Numbered filenames protect existing results.
If no seams are detected, no output file is created.

After selecting a video, choose one of the six shot types in the launcher
console. Each option includes a short explanation. Press Enter to keep the
tested standard settings, or enter 2-6 to use a different starting point.
Montage and dialogue presets ask for inspected, zero-based seam indices;
the dialogue preset also lets you choose whether to stretch audio.
Enter Q at any settings prompt to cancel before processing.
All presets use seven candidates and CRF 14, and the selected parameters are
displayed before processing starts.

The launcher uses `.venv\Scripts\python.exe` and the locally downloaded
`rife-v4.6` model. FFmpeg and FFprobe must be on PATH. To set it up again:

```powershell
uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_desktop_launcher.ps1
```

The installer will not overwrite an existing desktop launcher.
You can also run `launch.ps1` directly.

### 1. Find seams (optional inspection)

```bash
python3 find_seams.py input.mp4
```

Analyzes motion between consecutive frames and reports unusual jumps and any
detected periodicity, for example:

```text
22 suspicious seams found (transition from frame i -> i+1):
  Frame    95 ->    96   (t=  3.96s)   score=7.60
  ...
Likely periodicity: every ~24 frames (~1.00s at 24.0 fps)
```

Raw scores are also saved to `score_per_frame.csv` for manual inspection.

### 2. Repair the video (main script)

```bash
python3 insert_best_frame.py input.mp4 output.mp4 \
  --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe \
  --rife-model rife-ncnn-vulkan/rife-v4.6
```

The script:

1. Detects seams automatically using the same logic as `find_seams.py`.
2. Generates several RIFE candidates at different times between frames i and i+1.
3. Selects the candidate that distributes the remaining motion jump most evenly.
4. Inserts **exactly that one frame**, increasing the frame count by the number of seams.
5. Encodes the result once at high quality (CRF 14 by default) and stretches
   audio proportionally to maintain approximate synchronization.

**Key options:**

| Flag | Meaning |
|---|---|
| `--candidates N` | Candidate timestamps per seam (default: 7) |
| `--frames 95,119,...` | Supply seam indices manually instead of automatic detection |
| `--threshold` | Detection sensitivity; lower values are more sensitive |
| `--crf` | Final video quality; lower is better (default: 14) |
| `--workdir` | Intermediate-file directory (default: `<output>_work/`) |
| `--clean` | Refresh managed working files before running, for example after changing seams |
| `--no-stretch-audio` | Leave audio unchanged |
| `--include-scene-cuts` | Disable the automatic scene-cut filter |
| `--min-relative-jump` | Minimum increase over local motion (default: 0.10 = 10%) |
| `--no-periodic-recovery` | Do not recover weaker peaks on a confidently detected periodic grid |

### Starting parameters by shot type

The defaults were tested on a continuous, fast Seedance camera flight with fine
landscape textures, and the user confirmed a good result. Other combinations
below are reasoned starting points, **not presets validated across multiple
videos**. First inspect detections with `find_seams.py` using the same detection
parameters, then run the repair.

| Shot / situation | Starting parameters | Reason / what to watch for |
|---|---|---|
| Continuous FPV flight, tracking shot, or zoom with regular stutters | `--threshold 3 --min-relative-jump 0.10 --candidates 7 --crf 14` | Tested starting point. The minimum increase suppresses very weak outliers; periodic recovery remains enabled to find weaker peaks on a stable grid. |
| Quiet or nearly static shot with isolated suspicious transitions | `--threshold 4 --min-relative-jump 0.20 --no-periodic-recovery --candidates 7` | Conservative start to avoid adding frames for small fluctuations. Subtle real jumps can be missed; inspect detections visually. |
| Irregular action, pans, sudden acceleration, or strong lighting changes | `--threshold 3.5 --min-relative-jump 0.15 --no-periodic-recovery --candidates 7` | Normal motion or brightness peaks can resemble defects. Avoid recovery based on an assumed period; narrow questionable detections with `--frames`. |
| Visible small stutters missed by the defaults | `--threshold 2.5 --min-relative-jump 0.05 --no-periodic-recovery --candidates 7` | A more sensitive search that may admit more false positives. Use only for already visible jumps, not indiscriminately on every video. |
| Montage with real cuts or changing shots | Process shots separately, or use `--frames 95,119` with actually inspected indices | Keep the cut filter enabled. Manual indices bypass it, so never include an intentional cut. Do not copy the example indices without checking. |
| Dialogue / lip-synced audio | Start with `--frames ... --candidates 7`, then inspect picture and sound locally | Each insertion shifts the video timeline. Global audio stretching is approximate; no detection parameter guarantees lip sync. Use `--no-stretch-audio` only if audio will be adjusted or replaced separately. |

Unspecified values retain their defaults, particularly CRF 14 and the enabled
scene-cut filter. Detection criteria work together: lowering `--threshold`
alone does not help if the relative increase is still below its minimum.
There is no universal single sensitivity flag for shots with highly variable motion.

`--candidates 1` provides a fast preview using only `t=0.5`.
Keep 7 for final output: in the real-video test, `t=0.375` won at one seam,
while `t=0.5` was better at the others. More candidates do not change the
detected seam list or replace better detection. CRF controls encoding quality,
not repair strength.

Example of a conservative run on Windows:

```powershell
.\.venv\Scripts\python.exe find_seams.py input.mp4 --threshold 4 --min-relative-jump 0.20 --no-periodic-recovery
.\.venv\Scripts\python.exe insert_best_frame.py input.mp4 output.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe --rife-model rife-ncnn-vulkan/rife-v4.6 --threshold 4 --min-relative-jump 0.20 --no-periodic-recovery --candidates 7
```

The desktop launcher offers all six starting points above, with the defaults
selected by pressing Enter. For values beyond these presets, invoke the Python
script directly as shown above.

**Intermediate files** (extracted originals, all tested candidates, and the
final sequence) are saved in `<output>_work/` and are **not deleted automatically**.
This allows manual inspection or refinement and avoids repeating expensive
frame extraction on subsequent runs.

The cache is reused only when the input SHA-256 fingerprint and the complete
frame-file list with file sizes match. Interrupted extraction is restarted.
`--clean` refreshes only managed subdirectories; other working-directory files
are preserved. Nonempty directories without a project marker, including those
from older versions, are rejected: select a new working directory.
The input, output, and project must not be inside the working directory.
Candidates are stored separately under `candidates/seam_<index>/`; indices are zero-based.

Period estimation requires at least three equal intervals accounting for at
least 60% of the intervals, and reports this fraction. It does not prove a
model window size.

Detection combines a Z-score with a minimum increase so that tiny deviations in
nearly constant motion do not automatically trigger repairs. With at least four
strong detections on a stable period and phase, weaker peaks can be recovered.
Each still requires at least a 15% relative increase, 0.5 grayscale levels of
absolute increase, and a Z-score of at least 1 (or a lower explicitly chosen
threshold). A grid position alone is insufficient. The reported periodicity
fraction is based only on strong detections.
Reproduce the previous Z-score-only behavior with
`--min-relative-jump 0 --no-periodic-recovery`.

After successful encoding, `<output>_work/repair_report.json` records each seam's
chosen timestamp and motion scores before and after insertion.
Pixel difference is only a comparison metric, not proof of better perceived
quality or artifact-free interpolation.

### Local evaluation

```powershell
.\.venv\Scripts\python.exe evaluate_video.py input.mp4 --output .test-output/evaluation --candidates output_work/candidates
```

Produces JSON measurements and contact sheets. `--candidates` is optional.
To evaluate existing candidates, the extracted originals must also be present
in the adjacent `frames/` directory. Keep evaluations of private videos inside
the ignored `.test-output/` directory.

### Other scripts (older / alternative approaches)

- `fix_seams.py`: replaces two frames at each seam instead of inserting frames.
  Duration stays unchanged. Strong jumps can remain more abrupt than with
  `insert_best_frame.py`, because all motion must fit into the same short interval.
- `insert_seams.py`: inserts `factor - 1` frames per seam without selecting a
  single candidate. Predecessor to `insert_best_frame.py`.

Use **`insert_best_frame.py`** for the best results observed so far.
See `HANDOVER.md` for development history and reasoning.

## Known limitations

- The conservative scene-cut filter skips transitions with both large pixel
  differences and very different color distributions. It can miss cuts or
  misclassify strong lighting changes. Disable it with `--include-scene-cuts`;
  explicit `--frames` bypass the filter.
- For very large motion jumps (scores far above the rest, typically toward the
  end of long Seedance generations with accumulated drift), even the best RIFE
  candidate may not fully hide the discontinuity.

See `HANDOVER.md` for further context, open questions, and development ideas.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\smoke_pipeline.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\test_launcher.ps1
```

The second test requires FFmpeg, FFprobe, and a locally installed Windows RIFE.
It generates a short test video in `.test-output/`, checks frame count and
audio, and reruns processing to check cache reuse.

The PowerShell test checks all six launcher presets, default selection, manual
frame input, audio choices, invalid input, and cancellation without opening
dialogs or processing videos.

## Files in the public repository

Virtual environments, local settings, videos, generated frames, and downloaded
RIFE binaries/models are not versioned. Before the first run, download RIFE as
described under Installation and extract it into `rife-ncnn-vulkan/`.
Its README and license remain in the repository.
Tests generate their video data locally; private sample videos are not required.
