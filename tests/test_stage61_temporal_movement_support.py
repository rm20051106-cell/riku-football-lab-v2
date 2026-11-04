import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "build_movement_candidates")
NS = {}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage61-supported-movement>", "exec"), NS)
build = NS["build_movement_candidates"]


class Stage61TemporalMovementSupportTests(unittest.TestCase):
    @staticmethod
    def frame(t, speed):
        return {
            "time_seconds": t,
            "left_foot_image_motion_per_sec": speed,
            "right_foot_image_motion_per_sec": None,
        }

    def test_single_frame_spike_without_neighbor_support_is_rejected(self):
        frames = [
            self.frame(0, 0.01),
            self.frame(1, 0.30),
            self.frame(2, 0.01),
            self.frame(3, 0.01),
            self.frame(4, 0.01),
        ]
        self.assertEqual(build({"sampling_interval_seconds": 1, "frames": frames}), [])

    def test_peak_with_adjacent_motion_support_is_retained_as_candidate(self):
        frames = [
            self.frame(0, 0.12),
            self.frame(1, 0.30),
            self.frame(2, 0.11),
            self.frame(3, 0.02),
        ]
        result = build({"sampling_interval_seconds": 1, "frames": frames})
        self.assertTrue(result)
        self.assertEqual(result[0]["time_seconds"], 1.0)
        self.assertFalse(result[0]["is_football_action_confirmed"])

    def test_missing_sample_gap_cannot_support_a_peak(self):
        frames = [
            self.frame(0, 0.01),
            self.frame(1, 0.30),
            self.frame(3, 0.12),
            self.frame(4, 0.02),
            self.frame(5, 0.01),
        ]
        result = build({"sampling_interval_seconds": 1, "frames": frames})
        self.assertFalse(any(item["time_seconds"] == 1.0 for item in result))

    def test_inferred_sampling_interval_supports_regular_samples(self):
        frames = [self.frame(float(i), 0.1 + i * 0.01) for i in range(6)]
        result = build({"frames": frames})
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
