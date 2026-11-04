import ast
import math
import pathlib
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def phase_builder():
    return next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                and node.name == "build_kick_phase_candidates")


class Stage53KickSampleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = phase_builder()
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"np": SimpleNamespace(isfinite=math.isfinite)}
        exec(compile(module, "<kick-phase-builder>", "exec"), namespace)
        cls.build = staticmethod(namespace["build_kick_phase_candidates"])

    @staticmethod
    def frames(speeds, times=None):
        times = times or [i * 0.5 for i in range(len(speeds))]
        return [
            {"time_seconds": timestamp,
             "right_foot_image_motion_per_sec": speed,
             "left_foot_image_motion_per_sec": 0.1}
            for speed, timestamp in zip(speeds, times)
        ]

    def test_nonpositive_or_nonfinite_sampling_interval_disables_candidates(self):
        frames = self.frames([0.1, 0.4, 1.0, 0.2, 0.1])
        for interval in (0, -0.5, float("nan"), float("inf")):
            with self.subTest(interval=interval):
                result = self.build(frames, interval, "right")
                self.assertIsNone(result["preferred_foot_peak_candidate"])
                self.assertEqual(result["feet"]["right"]["status"], "insufficient_sampling")
                self.assertEqual(result["sampling_interval_seconds"], 0.0)

    def test_nonfinite_timestamp_is_excluded_from_sample_count(self):
        frames = self.frames([0.1, 0.4, 1.0, 0.2, 0.1])
        frames[1]["time_seconds"] = float("nan")
        result = self.build(frames, 0.5, "right")
        self.assertEqual(result["feet"]["right"]["sample_count"], 4)
        self.assertIsNone(result["preferred_foot_peak_candidate"])

    def test_negative_motion_is_excluded_but_valid_samples_remain(self):
        result = self.build(self.frames([0.1, 0.4, 1.0, 0.2, -2.0]), 0.5, "right")
        self.assertEqual(result["feet"]["right"]["sample_count"], 4)
        self.assertIsNotNone(result["preferred_foot_peak_candidate"])

    def test_out_of_order_neighbor_timestamp_cannot_support_peak(self):
        frames = self.frames(
            [0.1, 0.4, 1.0, 0.2, 0.1],
            [0.0, 1.0, 0.5, 1.5, 2.0],
        )
        result = self.build(frames, 0.5, "right")
        self.assertIsNone(result["preferred_foot_peak_candidate"])
        self.assertEqual(result["feet"]["right"]["status"], "insufficient_peak_support")

    def test_boolean_motion_and_timestamp_values_are_not_measurements(self):
        frames = self.frames([0.1, 0.4, 1.0, 0.2, 0.1])
        frames[0]["right_foot_image_motion_per_sec"] = True
        frames[4]["time_seconds"] = False
        result = self.build(frames, 0.5, "right")
        self.assertEqual(result["feet"]["right"]["sample_count"], 3)
        self.assertIsNone(result["preferred_foot_peak_candidate"])


if __name__ == "__main__":
    unittest.main()
