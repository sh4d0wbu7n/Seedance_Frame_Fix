import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import seam_utils as utils
from find_seams import cluster_period
from fix_seams import replacement_plan
from insert_best_frame import find_best_candidate


class RegressionTests(unittest.TestCase):
    def test_period_requires_repeated_majority(self):
        self.assertIsNone(cluster_period([0, 24])[0])
        self.assertIsNone(cluster_period([0, 8, 21, 45, 81])[0])
        self.assertEqual(cluster_period([0, 24, 48, 72])[0], 24)

    def test_argument_validation(self):
        for value in ('0', '-2'):
            with self.assertRaises(argparse.ArgumentTypeError):
                utils.positive_int(value)
        for value in ('-1', 'abc', '', '1,'):
            with self.assertRaises(argparse.ArgumentTypeError):
                utils.frame_indices(value)
        for indices in ([-1], [9], [10]):
            with self.assertRaises(ValueError):
                utils.validate_frames(indices, 10)
        self.assertEqual(utils.frame_indices('3, 1,3'), [1, 3])

    def test_pad_and_clamped_boundaries(self):
        plan = replacement_plan([5], 2, 20)
        self.assertEqual(plan[5], (3, 8, 0.4))
        self.assertEqual(plan[6], (3, 8, 0.6))
        self.assertEqual(replacement_plan([0], 2, 20), {1: (0, 3, 1 / 3)})

    def test_cut_vs_motion(self):
        black = np.zeros((90, 160, 3), np.uint8)
        white = np.full_like(black, 255)
        self.assertTrue(utils.is_scene_cut(black, white))
        image = black.copy()
        image[20:60, 20:60] = 255
        shifted = np.roll(image, 20, axis=1)
        self.assertFalse(utils.is_scene_cut(image, shifted))

    def test_workdir_protects_unowned_data_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input.mp4'
            source.write_bytes(b'original')
            with self.assertRaises(ValueError):
                utils.prepare_workdir(root, source, root / 'out.mp4')
            unowned = root / 'unowned'
            unowned.mkdir()
            (unowned / 'important.txt').write_text('keep')
            with self.assertRaises(ValueError):
                utils.prepare_workdir(unowned, source, root / 'out.mp4')
            self.assertTrue((unowned / 'important.txt').exists())
            owned = utils.prepare_workdir(root / 'work', source, root / 'out.mp4')
            (owned / 'notes.txt').write_text('keep')
            utils.reset_owned_dir(owned, 'frames')
            self.assertTrue((owned / 'notes.txt').exists())
            with self.assertRaises(ValueError):
                utils.reset_owned_dir(owned, '..')

    def test_cache_rejects_changed_source_and_interrupted_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'input.mp4'
            source.write_bytes(b'first')
            root = utils.prepare_workdir(base / 'work', source, base / 'out.mp4')
            def extract(*args, **kwargs):
                (root / 'frames' / 'frame_000001.png').write_bytes(b'png')
            with patch.object(utils.subprocess, 'run', side_effect=extract) as run:
                utils.cached_frames(root, source)
                utils.cached_frames(root, source)
                self.assertEqual(run.call_count, 1)
                source.write_bytes(b'other')
                utils.cached_frames(root, source)
                self.assertEqual(run.call_count, 2)
                (root / 'frames.json').unlink()
                utils.cached_frames(root, source)
                self.assertEqual(run.call_count, 3)
                (root / 'frames' / 'frame_000001.png').write_bytes(b'')
                utils.cached_frames(root, source)
                self.assertEqual(run.call_count, 4)
                utils.cached_frames(root, source, clean=True)
                self.assertEqual(run.call_count, 5)

    def test_candidates_remain_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / 'a.png', root / 'b.png'
            cv2.imwrite(str(a), np.zeros((16, 16, 3), np.uint8))
            cv2.imwrite(str(b), np.full((16, 16, 3), 200, np.uint8))
            def interpolate(a, b, output, t, *args):
                cv2.imwrite(str(output), np.full((16, 16, 3), int(200 * t), np.uint8))
            with patch('insert_best_frame.run_rife', side_effect=interpolate):
                for seam in (5, 10):
                    result = find_best_candidate(a, b, 3, 'rife', None, root / f'seam_{seam:06d}')
                    self.assertEqual(result[1], 0.5)
            self.assertEqual(len(list(root.glob('seam_*/cand_*.png'))), 6)


if __name__ == '__main__':
    unittest.main()
