import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "build_movement_candidates")
NS = {}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage57-movement>", "exec"), NS)
build = NS["build_movement_candidates"]


class Stage57MovementCandidateValidationTests(unittest.TestCase):
    @staticmethod
    def frame(t, left=None, right=None):
        return {
            "time_seconds": t,
            "left_foot_image_motion_per_sec": left,
            "right_foot_image_motion_per_sec": right,
        }

    def test_rejects_boolean_nonfinite_negative_and_malformed_values(self):
        frames = [
            self.frame(0, True, None),
            self.frame(1, float("nan"), -0.4),
            self.frame(2, float("inf"), "0.3"),
            self.frame(3, 0.08, None),
            self.frame(4, None, 0.09),
            self.frame(5, 0.1, None),
        ]
        result = build({"frames": frames})
        self.assertEqual([x["time_seconds"] for x in result], [3.0, 4.0, 5.0])
        self.assertTrue(all(x["is_football_action_confirmed"] is False for x in result))

    def test_rejects_invalid_timestamps_and_non_dictionary_frames(self):
        frames = [
            self.frame(float("nan"), 0.2, 0.1),
            self.frame(float("inf"), 0.3, 0.1),
            self.frame(True, 0.4, 0.1),
            self.frame(-1, 0.5, 0.1),
            "bad-frame",
            self.frame(2, 0.08, None),
            self.frame(3, 0.09, None),
            self.frame(4, 0.1, None),
        ]
        result = build({"frames": frames})
        self.assertEqual([x["time_seconds"] for x in result], [2.0, 3.0, 4.0])

    def test_duplicate_timestamps_are_not_independent_samples(self):
        frames = [
            self.frame(1, 0.2, None),
            self.frame(1.0001, 0.3, None),
            self.frame(1.0002, 0.4, None),
            self.frame(2, 0.1, None),
        ]
        self.assertEqual(build({"frames": frames}), [])

    def test_non_dictionary_summary_and_invalid_limits_return_empty(self):
        self.assertEqual(build(None), [])
        self.assertEqual(build({"frames": []}), [])
        frames = [self.frame(0, 0.1), self.frame(1, 0.2), self.frame(2, 0.3)]
        self.assertEqual(build({"frames": frames}, max_events=0), [])
        self.assertEqual(build({"frames": frames}, max_events=True), [])

    def test_candidates_are_time_sorted_and_limited_to_eight(self):
        frames = [self.frame(float(i), 0.1 + i * 0.01) for i in range(90)]
        result = build({"frames": frames}, max_events=99)
        self.assertLessEqual(len(result), 8)
        times = [x["time_seconds"] for x in result]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(b - a >= 10 for a, b in zip(times, times[1:])))


if __name__ == "__main__":
    unittest.main()
