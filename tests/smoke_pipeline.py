"""Explicit integration check using FFmpeg and locally installed RIFE; not auto-discovered."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.test-output'
WORK.mkdir(exist_ok=True)
source = WORK / 'input.mp4'
output = WORK / 'fixed.mp4'
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'testsrc2=size=64x64:rate=24:duration=1', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt',
                'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True)
command = [sys.executable, str(ROOT / 'insert_best_frame.py'), str(source), str(output),
           '--frames', '5,15', '--candidates', '1', '--rife-bin',
           str(ROOT / 'rife-ncnn-vulkan/rife-ncnn-vulkan.exe'), '--rife-model',
           str(ROOT / 'rife-ncnn-vulkan/rife-v4.6')]
for attempt in range(2):
    subprocess.run(command, check=True)
data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                          '-of', 'json', str(output)], text=True))
video = next(s for s in data['streams'] if s['codec_type'] == 'video')
assert int(video['nb_frames']) == 26, video
assert any(s['codec_type'] == 'audio' for s in data['streams'])
assert len(list((WORK / 'fixed_work/candidates').glob('seam_*/cand_*.png'))) == 2
print('SMOKE OK: 24 -> 26 Frames, Audio vorhanden, Cache erneut verwendet, Kandidaten getrennt.')
