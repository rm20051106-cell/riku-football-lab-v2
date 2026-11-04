import json
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage49VisibilityQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = HTML.index("function buildAiFormAutoScore(")
        end = HTML.index("\nfunction renderAiFormAutoScore", start)
        cls.function_source = HTML[start:end]

    def evaluate(self, summary, angle="右側から"):
        script = self.function_source + "\nconst result=buildAiFormAutoScore(" + json.dumps(summary, ensure_ascii=False) + "," + json.dumps(angle, ensure_ascii=False) + ");console.log(JSON.stringify(result));"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_single_visible_frame_is_not_enough_to_score(self):
        frame = {"right_knee_angle_deg": 160, "metric_quality": {"right_knee": "measured"}}
        result = self.evaluate({"frames": [frame]})
        self.assertIsNone(result["score"])
        self.assertEqual(result["measured"], 0)
        self.assertEqual(result["minimumSamples"], 2)

    def test_sparse_visibility_across_long_clip_is_excluded(self):
        frames = [{"right_knee_angle_deg": 160, "metric_quality": {"right_knee": "measured"}}]
        frames.extend({} for _ in range(9))
        result = self.evaluate({"frames": frames})
        self.assertIsNone(result["score"])
        self.assertEqual(result["minimumSamples"], 4)

    def test_repeated_visible_samples_are_eligible_for_reference_score(self):
        frames = [
            {"right_knee_angle_deg": value, "metric_quality": {"right_knee": "measured"}}
            for value in (160, 161, 159, 160)
        ]
        result = self.evaluate({"frames": frames})
        self.assertIsNotNone(result["score"])
        self.assertEqual(result["measured"], 1)
        self.assertEqual(result["minimumSamples"], 2)
        self.assertNotIn("右膝角度", result["missing"])

    def test_rear_view_does_not_score_trunk_angle(self):
        frames = [
            {"right_knee_angle_deg": 160, "left_knee_angle_deg": 160,
             "right_hip_angle_deg": 170, "left_hip_angle_deg": 170,
             "trunk_lean_image_angle_deg": 5}
            for _ in range(4)
        ]
        result = self.evaluate({"frames": frames}, "後ろから")
        self.assertEqual(result["total"], 4)
        self.assertNotIn("体幹傾き", result["missing"])

    def test_capture_quality_retake_status_blocks_reference_score(self):
        frames = [
            {"right_knee_angle_deg": 160, "metric_quality": {"right_knee": "measured"}}
            for _ in range(4)
        ]
        result = self.evaluate({
            "frames": frames,
            "capture_quality": {
                "status": "retake_recommended_joint_visibility",
                "guidance": "複数の関節が映っていません。",
            },
        })
        self.assertIsNone(result["score"])
        self.assertTrue(result["captureBlocked"])
        self.assertIn("関節", result["note"])

    def test_low_video_pose_detection_blocks_reference_score(self):
        frames = [
            {"right_knee_angle_deg": 160, "metric_quality": {"right_knee": "measured"}}
            for _ in range(4)
        ]
        result = self.evaluate({
            "frames": frames,
            "video_scan_quality": {
                "status": "retake_recommended_low_detection",
                "pose_detection_rate": 0.1,
                "guidance": "姿勢検出率が低いです。",
            },
        })
        self.assertIsNone(result["score"])
        self.assertTrue(result["captureBlocked"])

    def test_video_pose_detection_rate_scales_reference_quality_score(self):
        frames = [
            {"right_knee_angle_deg": value, "metric_quality": {"right_knee": "measured"}}
            for value in (160, 161, 159, 160)
        ]
        full = self.evaluate({"frames": frames})
        partial = self.evaluate({
            "frames": frames,
            "video_scan_quality": {
                "status": "usable_with_caution_low_detection",
                "pose_detection_rate": 0.5,
            },
        })
        self.assertEqual(partial["detectionRate"], 0.5)
        self.assertEqual(partial["score"], round(full["score"] * 0.5))

    def test_legacy_frames_without_metric_quality_remain_compatible(self):
        frames = [{"right_knee_angle_deg": 160} for _ in range(3)]
        result = self.evaluate({"frames": frames})
        self.assertEqual(result["measured"], 1)
        self.assertIsNotNone(result["score"])


if __name__ == "__main__":
    unittest.main()
