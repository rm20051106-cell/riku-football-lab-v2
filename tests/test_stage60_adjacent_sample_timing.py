import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "has_adjacent_sample_timing")
NS = {}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage60-adjacent-time>", "exec"), NS)
valid = NS["has_adjacent_sample_timing"]


class Stage60AdjacentSampleTimingTests(unittest.TestCase):
    def test_normal_adjacent_sample_is_accepted(self):
        self.assertTrue(valid(2.0, 1.5, 0.5))

    def test_missing_sample_gap_is_rejected(self):
        self.assertFalse(valid(2.5, 1.5, 0.5))

    def test_match_scan_interval_allows_normal_four_second_samples(self):
        self.assertTrue(valid(8.0, 4.0, 4.0))
        self.assertFalse(valid(12.5, 4.0, 4.0))

    def test_out_of_order_and_equal_timestamps_are_rejected(self):
        self.assertFalse(valid(1.0, 2.0, 0.5))
        self.assertFalse(valid(2.0, 2.0, 0.5))

    def test_nonfinite_boolean_and_nonpositive_intervals_are_rejected(self):
        self.assertFalse(valid(float("nan"), 0.0, 0.5))
        self.assertFalse(valid(float("inf"), 0.0, 0.5))
        self.assertFalse(valid(True, 0.0, 0.5))
        self.assertFalse(valid(1.0, 0.0, 0.0))
        self.assertFalse(valid(1.0, 0.0, -0.5))


if __name__ == "__main__":
    unittest.main()
