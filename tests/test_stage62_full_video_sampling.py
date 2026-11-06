import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "build_match_sampling_plan")
NS = {"MATCH_SAMPLE_RATE": 1.0, "MATCH_MAX_SAMPLES": 1200}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage62-match-sampling>", "exec"), NS)
build = NS["build_match_sampling_plan"]
OCR_NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "should_run_match_jersey_ocr")
OCR_NS = {}
exec(compile(ast.Module(body=[OCR_NODE], type_ignores=[]), "<stage62-ocr-cadence>", "exec"), OCR_NS)
should_run_ocr = OCR_NS["should_run_match_jersey_ocr"]
ITER_NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "iter_sampled_video_frames")
ITER_NS = {}
exec(compile(ast.Module(body=[ITER_NODE], type_ignores=[]), "<stage62-frame-iterator>", "exec"), ITER_NS)
iterate_frames = ITER_NS["iter_sampled_video_frames"]


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
    def test_fifteen_minute_video_is_scanned_at_two_second_intervals(self):
        plan = build(30, 30 * 60 * 15)
        self.assertEqual(plan["frame_interval"], 30)
        self.assertEqual(plan["sampling_interval_seconds"], 1.0)
        self.assertEqual(plan["sample_limit"], 1200)
        self.assertEqual(plan["estimated_samples"], 900)

    def test_twenty_minute_video_uses_all_six_hundred_samples_and_reaches_end(self):
        plan = build(30, 30 * 60 * 20)
        self.assertEqual(plan["sample_limit"], 1200)
        self.assertEqual(plan["estimated_samples"], 600)
        self.assertEqual(plan["sampling_interval_seconds"], 1.0)
        self.assertAlmostEqual((plan["estimated_samples"] - 1) * plan["sampling_interval_seconds"], 1198.0)

    def test_twenty_five_fps_video_keeps_two_second_sampling(self):
        plan = build(25, 25 * 60 * 20)
        self.assertEqual(plan["frame_interval"], 25)
        self.assertEqual(plan["sample_limit"], 1200)

    def test_short_video_uses_only_samples_that_exist(self):
        plan = build(30, 30 * 45)
        self.assertEqual(plan["sample_limit"], 1200)
        self.assertEqual(plan["estimated_samples"], 45)

    def test_sample_cap_is_bounded_even_if_configuration_is_excessive(self):
        plan = build(30, 30 * 60 * 20, target_rate=4, max_samples=99999)
        self.assertEqual(plan["sampling_rate_fps"], 1.0)
        self.assertEqual(plan["sample_limit"], 1200)
        self.assertEqual(plan["estimated_samples"], 1200)

    def test_invalid_fps_uses_safe_configured_interval(self):
        plan = build(float("nan"), 0)
        self.assertEqual(plan["frame_interval"], 1)
        self.assertEqual(plan["sampling_interval_seconds"], 2.0)
        self.assertEqual(plan["sample_limit"], 600)
        self.assertIsNone(plan["estimated_samples"])

    def test_iterator_scans_fifteen_minutes_to_actual_eof(self):
        capture = FakeCapture(30 * 60 * 15)
        samples = list(iterate_frames(capture, 30, 1200))
        self.assertEqual(len(samples), 900)
        self.assertEqual(samples[0], (0, 0))
        self.assertEqual(samples[-1], (26970, 26970))
        self.assertEqual(capture.position, 27000)

    def test_iterator_scans_twenty_minutes_without_truncating_the_last_sample(self):
        capture = FakeCapture(30 * 60 * 20)
        samples = list(iterate_frames(capture, 30, 1200))
        self.assertEqual(len(samples), 1200)
        self.assertEqual(samples[-1], (35970, 35970))
        self.assertEqual(capture.position, 36000)

    def test_iterator_stops_at_real_eof_for_short_video(self):
        capture = FakeCapture(125)
        samples = list(iterate_frames(capture, 30, 1200))
        self.assertEqual([item[0] for item in samples], [0, 30, 60, 90, 120])
        self.assertEqual(capture.position, 125)

    def test_iterator_respects_hard_sample_ceiling(self):
        capture = FakeCapture(30 * 60 * 30)
        samples = list(iterate_frames(capture, 30, 1200))
        self.assertEqual(len(samples), 1200)
        self.assertEqual(samples[-1][0], 35970)

    def test_jersey_ocr_is_throttled_to_first_and_every_fifth_sample(self):
        self.assertTrue(should_run_ocr(1))
        self.assertFalse(should_run_ocr(2))
        self.assertFalse(should_run_ocr(4))
        self.assertTrue(should_run_ocr(5))
        self.assertTrue(should_run_ocr(10))
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
        iterator_attributes = {n.attr for n in ast.walk(ITER_NODE) if isinstance(n, ast.Attribute)}
        self.assertIn("grab", iterator_attributes)


if __name__ == "__main__":
    unittest.main()
