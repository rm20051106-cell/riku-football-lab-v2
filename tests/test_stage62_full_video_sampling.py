import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_function(name, namespace=None):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    target = {} if namespace is None else namespace
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"<{name}>", "exec"), target)
    return node, target[name]


build_node, build = load_function(
    "build_match_sampling_plan",
    {"MATCH_SAMPLE_RATE": 2.0, "MATCH_MAX_SAMPLES": 2400},
)
iterator_node, iterate_frames = load_function("iter_sampled_video_frames")
ocr_node, should_run_ocr = load_function("should_run_match_jersey_ocr")


class FakeCapture:
    def __init__(self, frame_count):
        self.frame_count = frame_count
        self.position = 0

    def read(self):
        if self.position >= self.frame_count:
            return False, None
        frame = self.position
        self.position += 1
        return True, frame

    def grab(self):
        if self.position >= self.frame_count:
            return False
        self.position += 1
        return True


class Stage62FullVideoSamplingTests(unittest.TestCase):
    def test_fifteen_minute_video_uses_two_fps_and_1800_samples(self):
        plan = build(30, 30 * 60 * 15)
        self.assertEqual(plan["frame_interval"], 15)
        self.assertEqual(plan["sampling_interval_seconds"], 0.5)
        self.assertEqual(plan["sampling_rate_fps"], 2.0)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertEqual(plan["estimated_samples"], 1800)

    def test_twenty_minute_video_uses_two_fps_and_2400_samples(self):
        plan = build(30, 30 * 60 * 20)
        self.assertEqual(plan["frame_interval"], 15)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertEqual(plan["estimated_samples"], 2400)
        self.assertEqual(plan["sampling_interval_seconds"], 0.5)
        self.assertAlmostEqual((plan["estimated_samples"] - 1) * plan["sampling_interval_seconds"], 1199.5)

    def test_twenty_five_fps_video_uses_near_half_second_sampling(self):
        plan = build(25, 25 * 60 * 20)
        self.assertEqual(plan["frame_interval"], 13)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertEqual(plan["estimated_samples"], 2308)
        self.assertAlmostEqual(plan["sampling_interval_seconds"], 0.52)

    def test_short_video_estimate_uses_only_frames_that_exist(self):
        plan = build(30, 30 * 45)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertEqual(plan["estimated_samples"], 90)

    def test_sample_rate_and_cap_are_bounded(self):
        plan = build(30, 30 * 60 * 20, target_rate=4, max_samples=99999)
        self.assertEqual(plan["sampling_rate_fps"], 2.0)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertEqual(plan["estimated_samples"], 2400)

    def test_invalid_fps_uses_safe_one_second_interval(self):
        plan = build(float("nan"), 0)
        self.assertEqual(plan["frame_interval"], 1)
        self.assertEqual(plan["sampling_interval_seconds"], 1.0)
        self.assertEqual(plan["sample_limit"], 2400)
        self.assertIsNone(plan["estimated_samples"])

    def test_iterator_scans_fifteen_minutes_to_actual_eof_at_two_fps(self):
        capture = FakeCapture(30 * 60 * 15)
        samples = list(iterate_frames(capture, 15, 2400))
        self.assertEqual(len(samples), 1800)
        self.assertEqual(samples[0], (0, 0))
        self.assertEqual(samples[-1], (26985, 26985))
        self.assertEqual(capture.position, 27000)

    def test_iterator_scans_twenty_minutes_without_truncating_last_sample(self):
        capture = FakeCapture(30 * 60 * 20)
        samples = list(iterate_frames(capture, 15, 2400))
        self.assertEqual(len(samples), 2400)
        self.assertEqual(samples[-1], (35985, 35985))
        self.assertEqual(capture.position, 36000)

    def test_iterator_stops_at_real_eof_for_short_video(self):
        capture = FakeCapture(125)
        samples = list(iterate_frames(capture, 15, 2400))
        self.assertEqual([item[0] for item in samples], [0, 15, 30, 45, 60, 75, 90, 105, 120])
        self.assertEqual(capture.position, 125)

    def test_iterator_respects_hard_sample_ceiling(self):
        capture = FakeCapture(30 * 60 * 30)
        samples = list(iterate_frames(capture, 15, 2400))
        self.assertEqual(len(samples), 2400)
        self.assertEqual(samples[-1][0], 35985)

    def test_jersey_ocr_is_throttled_to_first_and_every_tenth_sample(self):
        self.assertTrue(should_run_ocr(1))
        self.assertFalse(should_run_ocr(2))
        self.assertFalse(should_run_ocr(9))
        self.assertTrue(should_run_ocr(10))
        self.assertTrue(should_run_ocr(20))
        self.assertFalse(should_run_ocr(0))

    def test_match_scanner_uses_sampling_plan_and_sequential_iterator(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "process_match_video")
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.assertIn("build_match_sampling_plan", names)
        self.assertIn("iter_sampled_video_frames", names)
        self.assertIn("sample_limit", names)
        attributes = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        self.assertIn("grab", attributes)
        self.assertNotIn("set", attributes)
        iterator_attributes = {n.attr for n in ast.walk(iterator_node) if isinstance(n, ast.Attribute)}
        self.assertIn("grab", iterator_attributes)

    def test_match_scanner_applies_ocr_cadence(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "process_match_video")
        calls = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "should_run_match_jersey_ocr"
        ]
        self.assertTrue(calls)

    def test_ci_keeps_webkit_for_explicit_safari_regression_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "stage56-validation.yml").read_text(encoding="utf-8")
        browser_tests = (ROOT / "tests" / "test_browser_e2e.py").read_text(encoding="utf-8")
        self.assertIn("python -m playwright install chromium webkit", workflow)
        self.assertIn("self.playwright.chromium.launch", browser_tests)
        self.assertIn("self.playwright.webkit.launch", browser_tests)


if __name__ == "__main__":
    unittest.main()
