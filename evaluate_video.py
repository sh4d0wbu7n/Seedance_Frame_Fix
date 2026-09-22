"""Local seam/candidate diagnostics; reports and contact sheets stay in an ignored workdir."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from insert_best_frame import find_jumps, frame_diff_score
from seam_utils import is_scene_cut


def evaluate(source, output, candidates=None):
    output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(source))
    fps = cap.get(cv2.CAP_PROP_FPS)
    images = []
    while True:
        ok, image = cap.read()
        if not ok:
            break
        h, w = image.shape[:2]
        images.append(cv2.resize(image, (320, round(h * 320 / w))))
    cap.release()
    if len(images) < 2:
        raise ValueError('Video contains fewer than two decoded frames.')
    scores = np.array([frame_diff_score(a, b) for a, b in zip(images, images[1:])])
    jumps = find_jumps(scores, 3.0)
    rows = []
    for index, (a, b) in enumerate(zip(images, images[1:])):
        hist = []
        for image in (a, b):
            h = cv2.calcHist([image], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
            hist.append(cv2.normalize(h, h, norm_type=cv2.NORM_L1))
        neighborhood = np.delete(scores[max(0, index - 7):index + 8], min(index, 7))
        row = {'index': index, 'seconds': (index + 1) / fps, 'score': float(scores[index]),
               'local_median': float(np.median(neighborhood)),
               'hist_distance': float(cv2.compareHist(*hist, cv2.HISTCMP_BHATTACHARYYA)),
               'rgb_difference': float(cv2.absdiff(a, b).mean()) / 255,
               'detected': index in jumps, 'scene_cut': bool(is_scene_cut(a, b))}
        if candidates:
            results = []
            paths = sorted((candidates / f'seam_{index:06d}').glob('cand_*.png'))
            if paths:
                originals = candidates.parent / 'frames'
                source_a = cv2.imread(str(originals / f'frame_{index + 1:06d}.png'))
                source_b = cv2.imread(str(originals / f'frame_{index + 2:06d}.png'))
                if source_a is None or source_b is None:
                    raise ValueError('Candidate evaluation requires original extracted frames.')
                row['candidate_original_gap'] = frame_diff_score(source_a, source_b)
            for path in paths:
                candidate = cv2.imread(str(path))
                left, right = frame_diff_score(source_a, candidate), frame_diff_score(candidate, source_b)
                results.append({'file': path.name, 'left': left, 'right': right, 'worst': max(left, right)})
            if results:
                row['candidates'] = results
                row['best'] = min(results, key=lambda r: r['worst'])
                row['reduction'] = 1 - row['best']['worst'] / max(row['candidate_original_gap'], 1e-6)
        rows.append(row)
    interesting = sorted(set(jumps) | set(np.argsort(scores)[-8:].tolist()))
    for page in range(0, len(interesting), 6):
        selected = interesting[page:page + 6]
        tiles = []
        for index in selected:
            pair = np.hstack([images[index], images[index + 1]])
            tile = cv2.copyMakeBorder(pair, 30, 0, 0, 0, cv2.BORDER_CONSTANT)
            label = f'{index}->{index+1}  diff={scores[index]:.2f} hist={rows[index]["hist_distance"]:.2f}'
            cv2.putText(tile, label, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(tile)
        cv2.imwrite(str(output / f'transitions_{page // 6 + 1}.jpg'), np.vstack(tiles))
    report = {'frames': len(images), 'fps': fps, 'jumps': jumps, 'transitions': rows}
    (output / 'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'frames': len(images), 'jumps': jumps,
                      'largest': sorted(rows, key=lambda r: r['score'], reverse=True)[:8],
                      'candidate_summary': [{k: r[k] for k in ('index', 'score', 'best', 'reduction')}
                                            for r in rows if 'best' in r]}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('.test-output/evaluation'))
    parser.add_argument('--candidates', type=Path)
    args = parser.parse_args()
    evaluate(args.source, args.output, args.candidates)
