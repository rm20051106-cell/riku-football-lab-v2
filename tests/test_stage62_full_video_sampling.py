import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "build_match_sampling_plan")
NS = {"MATCH_SAMPLE_RATE": 0.5, "MATCH_MAX_SAMPLES": 600}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage62-match-sampling>", "exec"), NS)
build = NS["build_match_sampling_plan"]


class Stage62FullVideoSamplingTests(unittest.TestCase):
    def test_fifteen_minute_video_is_scanned_at_two_second_intervals(self):
        plan = build(30, 30 * 60 * 15)
        self.assertEqual(plan["frame_interval"], 60)
        self.assertEqual(plan["sampling_interval_seconds"], 2.0)
        self.assertEqual(plan["sample_limit"], 450)

    def test_twenty_minute_video_uses_all_six_hundred_samples_and_reaches_end(self):
        plan = build(30, 30 * 60 * 20)
        self.assertEqual(plan["sample_limit"], 600)
        self.assertEqual(plan["sampling_interval_seconds"], 2.0)
        self.assertAlmostEqual((plan["sample_limit"] - 1) * plan["sampling_interval_seconds"], 1198.0)

    def test_twenty_five_fps_video_keeps_two_second_sampling(self):
        plan = build(25, 25 * 60 * 20)
        self.assertEqual(plan["frame_interval"], 50)
        self.assertEqual(plan["sample_limit"], 600)

    def test_short_video_uses_only_samples_that_exist(self):
        plan = build(30, 30 * 45)
        self.assertEqual(plan["sample_limit"], 23)

    def test_sample_cap_is_bounded_even_if_configuration_is_excessive(self):
        plan = build(30, 30 * 60 * 20, target_rate=4, max_samples=99999)
        self.assertEqual(plan["sampling_rate_fps"], 1.0)
        self.assertEqual(plan["sample_limit"], 1200)

    def test_invalid_fps_uses_safe_configured_interval(self):
        plan = build(float("nan"), 0)
        self.assertEqual(plan["frame_interval"], 2)
        self.assertEqual(plan["sampling_interval_seconds"], 2.0)
        self.assertEqual(plan["sample_limit"], 600)

    def test_match_scanner_uses_plan_and_sequential_grabs_not_repeated_random_seeks(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "process_match_video")
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.assertIn("build_match_sampling_plan", names)
        self.assertIn("sample_limit", names)
        self.assertIn("interval", names)
        self.assertIn("exhausted", names)
        attributes = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        self.assertIn("grab", attributes)
        self.assertNotIn("set", attributes)


if __name__ == "__main__":
    unittest.main()
