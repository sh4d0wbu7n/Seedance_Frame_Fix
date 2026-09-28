# Handover / Context for future development

## Real-video evaluation: procedure, results, and reasoning

Local testing used `Seedance_long.mp4`: 1920x1080, 24 fps, 601 frames,
25.041667 seconds of video, with an audio track. The source is private and
is not committed. Its name identifies the local test only; the program has
no filename-specific behavior or hard-coded seam indices.

### What was tested, and why?

1. **Measure the original and the unchanged algorithm.** FFprobe checked frame
   count, frame rate, resolution, and audio. `find_seams.py` provided raw scores;
   a full baseline run generated seven RIFE candidates per detection. This
   establishes a comparison before changes and avoids relying solely on
   subjective impressions.
2. **Inspect detections and missed peaks.** Contact sheets showed neighboring
   original frames. Local medians, Z-scores, and color distributions helped
   distinguish weak statistical outliers from larger motion changes.
   Detections at indices 122 and 278 were only about 6% and 4% above their
   local medians. Low local variance still made their Z-scores conspicuous.
   Four other local maxima (23, 47, 71, 575) lay on a clear 24-frame grid but
   were missed by the fixed Z-score threshold. These observations motivated
   a minimum increase and periodic recovery.
3. **Implement general rules instead of video-specific corrections.** Ordinary
   detections now require at least a 10% relative increase. Periodic recovery
   requires at least four strong detections, three equal intervals accounting
   for at least 60% of all intervals, and at least 80% phase agreement.
   Each recovered point must still be a local maximum with at least a 15%
   relative increase, 0.5 grayscale levels of absolute increase, and Z >= 1
   (or an explicitly lower threshold). A grid position alone is insufficient.
   Reported periodicity confidence uses only independently detected strong
   peaks, so recovered points do not artificially inflate it.
4. **Check candidate selection separately.** In the baseline, t=0.5 won at all
   22 seams. A quick improved run therefore initially used one candidate.
   The 20 shared seams were byte-identical to the best baseline candidates.
   The four new seams were then checked with seven candidates: t=0.375 won
   at index 23, and t=0.5 at the others. This is why seven candidates remain
   the default. The final sequence was assembled from these already computed
   winners and encoded once from PNGs, without another lossy intermediate pass.
5. **Validate the finished video.** FFprobe confirmed 625 frames at 24 fps
   (26.041667 seconds). Audio was present and approximately 26.03 seconds long.
   FFmpeg decoded all video and audio without reporting errors. Transition
   scores were measured again on the encoded result to distinguish candidate
   quality from encoding effects. A SHA-256 comparison with the extraction
   manifest confirmed that the original was unchanged.
6. **Guard against regressions.** Ten unit tests covered cache invalidation,
   interrupted extraction, working-directory protection, arguments, separate
   candidate storage, padding/boundary handling, the scene-cut heuristic,
   periodicity confidence, weak outliers, and evidence-based periodic recovery.
   The synthetic FFmpeg/RIFE smoke test checked 24 -> 26 frames, audio,
   cache reuse, and the new JSON repair report. All tests passed.

### Results and limits of the conclusions

The baseline inserted 22 frames (623 total). Improved detection removed two
weak detections and recovered four peaks: 24 insertions, 625 frames total.
The larger of the two remaining transition scores decreased by an average
of 30.8% for the PNG candidates and 28.7% in the final encoded video
(range: 18.5% to 42.8%). These figures compare repaired transitions against
their **original jumps**, not against the already repaired baseline video.

The metric is mean grayscale pixel difference after resizing to 320 pixels
wide and blurring. It is not an independent perceptual model and may favor
softer images. The assistant visually inspected contact sheets, not a full
real-time playback. The user subsequently explicitly rated the delivered
video as a very good result. The new thresholds were evaluated on **one**
real video plus synthetic tests. README starting values for other shot types
are reasoned suggestions, not measured presets. Global audio stretching remains
an approximation.

### Reproducible commands

Requires the project virtual environment, FFmpeg/FFprobe, and locally extracted
RIFE v4.6. Run from the project directory. Choose different output filenames
if your own results already exist.

```powershell
# Behavior before the minimum increase and periodic recovery:
.\.venv\Scripts\python.exe insert_best_frame.py Seedance_long.mp4 Seedance_long_baseline.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe --rife-model rife-ncnn-vulkan/rife-v4.6 --min-relative-jump 0 --no-periodic-recovery --candidates 7
# New default detection and final candidate selection:
.\.venv\Scripts\python.exe insert_best_frame.py Seedance_long.mp4 Seedance_long_improved.mp4 --rife-bin rife-ncnn-vulkan/rife-ncnn-vulkan.exe --rife-model rife-ncnn-vulkan/rife-v4.6 --candidates 7
# Local measurements/contact sheets and technical validation:
.\.venv\Scripts\python.exe evaluate_video.py Seedance_long.mp4 --output .test-output/evaluation --candidates Seedance_long_improved_work/candidates
ffprobe -v error -show_streams -show_format -of json Seedance_long_improved.mp4
ffmpeg -v error -i Seedance_long_improved.mp4 -f null -
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/smoke_pipeline.py
```

`evaluate_video.py` compares the original with existing PNG candidates.
Post-encoding measurements were performed separately for this test by mapping
inserted frames to their original transitions; this is not automatically part
of that tool. `repair_report.json` contains candidate metrics and run parameters.

After testing, the following generated artifacts were removed at the user's
request: both comparison videos, their `_work` directories, `.test-output/`
with contact sheets, measurements and one-off evaluation scripts,
`score_per_frame.csv`, and Python bytecode caches in the project/test directories.
The original video, `.venv`, RIFE, and reusable test/evaluation scripts were retained.

## Update: 2026-09-22

A subsequent real-video comparison found two very weak Z-score detections at
only a 4-6% motion increase, plus four missed local peaks on a stable 24-frame
grid. Shared detection in `seam_utils.py` now requires at least a 10% relative
increase and can recover periodic peaks with supporting evidence (optional).
All four scripts use the same detection implementation; their duplicate copies
were removed. `evaluate_video.py` and `repair_report.json` support reproducible
local comparisons without versioning private video data. The new thresholds
have been checked on one real video and synthetic tests, not a broad benchmark.

The historical sections below describe the original state.
Implemented since then: protected frame caching with input SHA-256 and a
completion manifest, marked working directories with limited cleanup, separate
candidates per seam, CLI validation, minimum periodicity confidence, and correct
`--pad` timestamps including boundary handling. `fix_seams.py` first generates
replacement frames from unchanged originals. With `--keep-frames`, the older
scripts use new unique directories so stale frames cannot remain.

All four scripts now use `seam_utils.py` for shared validation and/or the
scene-cut heuristic, so they can no longer be copied individually.
The conservative cut heuristic is enabled by default for automatic detection,
can be disabled with `--include-scene-cuts`, and is bypassed by manual
`--frames`. It has not yet been calibrated on a representative collection of
real Seedance videos. Regression tests and an explicit FFmpeg/RIFE smoke test
are in `tests/`. Windows startup uses `launch.ps1` or the installed desktop launcher.

This document is for a future LLM session (or yourself in a few months), to
continue development without repeating every dead end. Read it completely
before making changes: several seemingly obvious ideas have already been
tested and rejected for the reasons below.

## The initial problem

Seedance 2.5 videos show periodic stuttering: roughly every 24 frames
(about one second at 24 fps), motion jumps noticeably farther than between
the surrounding frames.

## What is NOT the cause (already ruled out)

1. **No duplicated/held frames.** The first hypothesis was that Seedance
   internally holds or duplicates frames like some other models.
   Tools such as "SeeFrame", which look for actual image duplicates, found
   none, correctly. The user's frame-by-frame inspection confirmed that
   neighboring images at the seams are not identical; motion simply jumps farther.

2. **Global interpolation is not a practical solution on its own**
   (`ffmpeg minterpolate` over the whole video, or fixed-factor RIFE
   interpolation throughout). It works in principle but is unnecessarily
   expensive when only about 20-30 of roughly 600 frames are affected.
   Targeted interpolation at detected seams provides the same pairwise RIFE
   quality because RIFE does not use context from the rest of the video
   (see "How RIFE works" below). There is no need to interpolate everywhere.

## The actual cause (historical diagnosis)

Video diffusion models such as Seedance generate temporal chunks/windows
rather than one continuous sequence (for example, a new window about every
24 frames). At chunk boundaries, limited context from the preceding section
can cause a small motion discontinuity: a genuine content jump, not a
compression or encoding artifact.

The evidence recorded at the time: `find_seams.py` measures motion strength
per transition using mean pixel difference after blurring, making it robust
against ordinary noise, and detects outliers using a local robust Z-score.
A real test video showed nearly perfect 24-frame periodicity across more
than 20 seams. Scores increased over time from about 7 to about 13, consistent
with accumulated drift in autoregressive generation.

**Caveat (historical):** At least one apparent seam in testing was an actual
**scene cut**, from fast FPV flight to a completely different static overhead
scene. At that stage, detection measured large motion jumps without identifying
their cause. In edited sequences, real cuts could be marked for repair even
though no smooth transition was intended. The open task was to distinguish
cuts from chunk artifacts automatically. The proposed cue was a much larger
absolute difference combined with dissimilar histograms/color distributions,
whereas a chunk jump remains within the same scene.

## Solution development (chronological, with reasoning)

1. **`fix_seams.py` v1: Farneback optical flow, replacing frames.**
   Replaced the two frames at each seam using classical optical-flow
   interpolation (`cv2.calcOpticalFlowFarneback`) between surrounding frames.
   **Result: poor.** The test footage was fast FPV drone flight over heather,
   with large, fast, repetitive foreground textures. Classical flow confused
   similar clumps of vegetation, producing visibly wavy/distorted trees and
   horizons. **Lesson: classical optical flow (Farneback/Lucas-Kanade) performs
   poorly on large, fast motion with repetitive textures.**

2. **`fix_seams.py` v2: RIFE instead of Farneback, still replacing frames.**
   The trained RIFE network substantially improved local image quality at
   seams. The overall video still looked degraded, however. The script wrote
   ALL frames, including roughly 580 untouched ones, through OpenCV's
   `VideoWriter` using the weak `mp4v` codec before final FFmpeg encoding.
   That added a lossy compression pass across the entire video.
   **Lesson: avoid unnecessary lossy intermediate video codecs in frame-accurate
   processing. Extract lossless PNGs, replace selected files, and encode once.**

3. **`fix_seams.py` v3: PNG pipeline, still replacing frames.**
   Fixed the quality loss from the previous stage. **User feedback: still
   stutters.** Replacing exactly two frames forces the entire, sometimes large,
   motion change into the original short time interval. For real content
   jumps, even a good interpolation model cannot always make that smooth.
   **Lesson: preserving the frame count has limited effectiveness for genuine
   content jumps; the transition needs more time.**

4. **`insert_seams.py`: inserting frames instead of replacing them (factor 4).**
   Automated the user's manual approach by adding three RIFE frames per seam.
   The longer transition looked subjectively smoother, including for genuine
   content jumps. It worked in principle, but the user had only wanted one
   added frame per seam. Factor 4 was originally used to provide more
   candidates for manual selection.

5. **`insert_best_frame.py`: the current approach, confirmed by the user as
   the best result so far.** Generates several RIFE candidates at different
   timestamps (default: seven, at 1/8 through 7/8 between frames i and i+1).
   Selects the candidate that distributes the remaining motion jump most
   evenly between i -> candidate and candidate -> i+1, minimizing the
   *larger* residual jump. Inserts only that one frame.
   This is the recommended approach; see `README.md`.

## How RIFE works (context for a future model replacement)

RIFE (Real-Time Intermediate Flow Estimation) is a trained CNN that estimates
motion flow at time t directly from two images, A and B, without a separate
classical optical-flow stage:

1. IFNet estimates flow from A and B toward time t at multiple resolutions,
   from coarse to fine.
2. Both images are warped toward time t using those flows.
3. A fusion network combines the warped images with a learned occlusion mask
   describing what is visible in A but hidden in B, and vice versa.

**Key property:** RIFE processes image pairs without context from the rest of
the video. Targeting only seam pairs therefore preserves pairwise interpolation
quality while reducing processing time.
[`rife-ncnn-vulkan`](https://github.com/nihui/rife-ncnn-vulkan) is the portable
command-line implementation used here. It runs through Vulkan on CPU/GPU
without a CUDA/PyTorch runtime.

## Open issues / development ideas (historical list)

The update above records which items have since been implemented.

- **Distinguish scene cuts from chunk jumps.** No automatic distinction existed
  when this list was written; see the discussion above.
- **The best-frame selection criterion is a proxy, not a perfect metric.**
  Mean pixel difference after blurring and downscaling to 320 pixels is fast
  but coarse. Possible alternatives include structural/perceptual similarity
  (SSIM/LPIPS) or optical-flow magnitude comparisons (such as RAFT), which might
  be more robust to brightness/contrast changes unrelated to motion.
- **Audio synchronization is approximate.** `--stretch-audio` uniformly adjusts
  the entire track using the tempo ratio `orig_duration / new_duration`.
  This works reasonably when seams occur regularly, typically every 24 frames.
  Irregularly distributed insertions make uniform stretching less accurate.
  Important lip-synced dialogue would need local audio adjustments, such as
  a short silent interval/crossfade per insertion, rather than global stretching.
- **No automated comparison/regression tests existed at this stage.**
  Results were visually checked by the user with frame exports.
  A small reference-video set with known seams and automated before/after
  residual-jump scores would support more systematic development.
- **More `--candidates` means linearly more RIFE calls.** There is one call per
  candidate, so cost scales with seams multiplied by candidates.
  Long videos could benefit from parallelism/batching. The RIFE directory
  mode supports multiple processing threads (`-j load:proc:save`), not yet used.
- **Very large jumps remain only partly corrected.** A possible extension is
  inserting extra frames only at particularly severe seams: a hybrid with
  `insert_seams.py` using a variable factor based on jump strength rather than
  one extra frame everywhere.

## Technical details / environment (historical state)

- Python 3 with `opencv-python-headless` and `numpy`; see `requirements.txt`.
- Detection: local robust Z-score on mean grayscale pixel differences, using
  a 15-frame window and median/MAD instead of mean/standard deviation so the
  jumps themselves do not dominate the statistics.
- The scripts were intentionally standalone, without a shared library, to
  remain easy to copy and understand individually. Further expansion would
  justify a shared `seam_utils.py` with `compute_motion_scores`, `find_jumps`,
  `run_rife`, and `ffprobe_*`. That refactoring had not yet been done at this
  historical stage; see the update above for the current shared module.
- Tested with `rife-ncnn-vulkan` release `20221029`, model `rife-v4.6`, suitable
  for general video. The tool default, `rife-v2.3`, is an older/weaker model.
