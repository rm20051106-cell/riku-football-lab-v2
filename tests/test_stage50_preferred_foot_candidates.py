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


class Stage50PreferredFootCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = phase_builder()
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"np": SimpleNamespace(isfinite=math.isfinite)}
        exec(compile(module, "<kick-phase-builder>", "exec"), namespace)
        cls.build = staticmethod(namespace["build_kick_phase_candidates"])

    def sample_frames(self):
        return [
            {"time_seconds": i * 0.5,
             "right_foot_image_motion_per_sec": speed,
             "left_foot_image_motion_per_sec": left}
            for i, (speed, left) in enumerate([(0.1, 0.2), (0.4, 0.1), (1.0, 0.1), (0.2, 0.1), (0.1, 0.1)])]
        ]

    def test_right_foot_is_default_focus_but_both_feet_are_preserved(self):
        result = self.build(self.sample_frames(), 0.5)
        self.assertEqual(result["preferred_kicking_foot"], "right")
        self.assertEqual(result["preferred_foot_peak_candidate"]["time_seconds"], 1.0)
        self.assertIsNotNone(result["opposite_foot_candidate"])
        self.assertEqual(result["phases"][2]["foot"], "right")
        self.assertEqual(result["phases"][2]["status"], "candidate_only")

    def test_left_foot_can_be_selected_without_losing_right_foot_data(self):
        result = self.build(self.sample_frames(), 0.5, "left")
        self.assertEqual(result["preferred_kicking_foot"], "left")
        self.assertEqual(result["preferred_foot_peak_candidate"]["time_seconds"], 0.0)
        self.assertIsNotNone(result["feet"]["right"]["peak_candidate"])

    def test_invalid_preferred_foot_falls_back_to_right(self):
        result = self.build(self.sample_frames(), 0.5, "unknown")
        self.assertEqual(result["preferred_kicking_foot"], "right")

    def test_impact_and_plant_are_never_claimed_as_ai_confirmed(self):
        result = self.build(self.sample_frames(), 0.5)
        phases = {item["key"]: item for item in result["phases"]}
        self.assertEqual(phases["plant"]["status"], "manual_review_required")
        self.assertEqual(phases["impact"]["status"], "manual_review_required")
        self.assertIsNone(phases["impact"]["time_seconds"])

    def test_coarse_sampling_still_disables_peak_candidates(self):
        result = self.build(self.sample_frames(), 1.0)
        self.assertIsNone(result["preferred_foot_peak_candidate"])
        self.assertEqual(result["feet"]["right"]["status"], "insufficient_sampling")


if __name__ == "__main__":
    unittest.main()
