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


class Stage52KickPeakSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = phase_builder()
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"np": SimpleNamespace(isfinite=math.isfinite)}
        exec(compile(module, "<kick-phase-builder>", "exec"), namespace)
        cls.build = staticmethod(namespace["build_kick_phase_candidates"])

    def test_peak_with_adjacent_motion_support_remains_candidate(self):
        speeds = [0.1, 0.4, 1.0, 0.2, 0.1]
        frames = [
            {"time_seconds": i * 0.5,
             "right_foot_image_motion_per_sec": speed,
             "left_foot_image_motion_per_sec": 0.1}
            for i, speed in enumerate(speeds)
        ]
        result = self.build(frames, 0.5, "right")
        candidate = result["preferred_foot_peak_candidate"]
        self.assertEqual(candidate["time_seconds"], 1.0)
        self.assertEqual(candidate["peak_support_samples"], 1)
        self.assertEqual(result["feet"]["right"]["status"], "candidate_only")

    def test_isolated_single_frame_spike_is_not_a_peak_candidate(self):
        speeds = [0.05, 0.06, 1.0, 0.04, 0.05]
        frames = [
            {"time_seconds": i * 0.5,
             "right_foot_image_motion_per_sec": speed,
             "left_foot_image_motion_per_sec": 0.05}
            for i, speed in enumerate(speeds)
        ]
        result = self.build(frames, 0.5, "right")
        self.assertIsNone(result["preferred_foot_peak_candidate"])
        self.assertEqual(result["feet"]["right"]["peak_support_samples"], 0)
        self.assertEqual(result["feet"]["right"]["status"], "insufficient_peak_support")
        phases = {item["key"]: item for item in result["phases"]}
        self.assertEqual(phases["swing"]["status"], "manual_review_required")

    def test_support_is_checked_per_foot_and_other_foot_data_is_preserved(self):
        frames = [
            {"time_seconds": i * 0.5,
             "right_foot_image_motion_per_sec": speed,
             "left_foot_image_motion_per_sec": left}
            for i, (speed, left) in enumerate([
                (0.05, 0.1), (0.06, 0.3), (1.0, 0.8), (0.04, 0.2), (0.05, 0.1)
            ])
        ]
        result = self.build(frames, 0.5, "left")
        self.assertIsNotNone(result["preferred_foot_peak_candidate"])
        self.assertIsNone(result["feet"]["right"]["peak_candidate"])
        self.assertEqual(result["preferred_kicking_foot"], "left")

    def test_coarse_sampling_disables_peak_even_with_support(self):
        frames = [
            {"time_seconds": i, "right_foot_image_motion_per_sec": value,
             "left_foot_image_motion_per_sec": value}
            for i, value in enumerate([0.1, 0.4, 1.0, 0.2, 0.1])
        ]
        result = self.build(frames, 1.0, "right")
        self.assertIsNone(result["preferred_foot_peak_candidate"])
        self.assertEqual(result["feet"]["right"]["status"], "insufficient_sampling")


if __name__ == "__main__":
    unittest.main()
