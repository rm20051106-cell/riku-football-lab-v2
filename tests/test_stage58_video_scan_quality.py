import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "build_video_scan_quality")
NS = {}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<stage58-scan-quality>", "exec"), NS)
build = NS["build_video_scan_quality"]


class Stage58VideoScanQualityTests(unittest.TestCase):
    def test_high_detection_rate_is_usable(self):
        result = build(10, 8)
        self.assertEqual(result["status"], "usable_for_review")
        self.assertEqual(result["pose_detection_rate"], 0.8)
        self.assertEqual(result["missed_pose_frames"], 2)

    def test_moderate_detection_rate_warns_about_selection_bias(self):
        result = build(10, 4)
        self.assertEqual(result["status"], "usable_with_caution_low_detection")
        self.assertIn("偏る", result["guidance"])

    def test_low_detection_rate_recommends_retake(self):
        result = build(20, 4)
        self.assertEqual(result["status"], "retake_recommended_low_detection")

    def test_less_than_three_pose_frames_is_insufficient(self):
        result = build(12, 2)
        self.assertEqual(result["status"], "insufficient_samples")

    def test_invalid_counts_are_safe_and_never_exceed_sampled_count(self):
        result = build(float("nan"), 50)
        self.assertIsNone(result["pose_detection_rate"])
        self.assertEqual(result["pose_detected_frames"], 0)
        result = build(4, 99)
        self.assertEqual(result["pose_detected_frames"], 4)
        self.assertEqual(result["missed_pose_frames"], 0)

    def test_boolean_and_negative_counts_are_not_accepted(self):
        result = build(True, -1)
        self.assertEqual(result["sampled_video_frames"], 0)
        self.assertEqual(result["pose_detected_frames"], 0)
        self.assertIsNone(result["pose_detection_rate"])


if __name__ == "__main__":
    unittest.main()
