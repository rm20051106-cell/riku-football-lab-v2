import ast
import math
import pathlib
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def quality_builder():
    return next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                and node.name == "build_form_capture_quality")


class Stage55FormEvidenceQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = quality_builder()
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"np": SimpleNamespace(isfinite=math.isfinite)}
        exec(compile(module, "<stage55-form-quality>", "exec"), namespace)
        cls.build = staticmethod(namespace["build_form_capture_quality"])

    @staticmethod
    def full_frame(height=0.62, confidence=0.9):
        names = [
            "left_shoulder", "right_shoulder", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle",
            "left_heel", "right_heel", "left_foot_index", "right_foot_index",
        ]
        return {
            "person_height_ratio": height,
            "landmarks": {name: [0.5, 0.5, confidence] for name in names},
            "left_knee_angle_deg": 160.0,
            "right_knee_angle_deg": 161.0,
            "left_hip_angle_deg": 170.0,
            "right_hip_angle_deg": 171.0,
            "trunk_lean_image_angle_deg": 8.0,
            "left_foot_image_motion_per_sec": 0.1,
            "right_foot_image_motion_per_sec": 0.2,
        }

    def test_complete_evidence_is_usable_and_reports_metric_coverage(self):
        result = self.build([self.full_frame() for _ in range(4)])
        self.assertEqual(result["status"], "usable_for_review")
        self.assertEqual(result["valid_person_size_samples"], 4)
        self.assertEqual(result["metric_sample_coverage"]["right_knee"]["coverage_rate"], 1.0)
        self.assertEqual(result["joint_visibility_rate"]["right_ankle"], 1.0)

    def test_missing_and_offscreen_joints_reduce_visibility_and_warn(self):
        frames = [self.full_frame() for _ in range(4)]
        for frame in frames[1:]:
            frame["landmarks"].pop("right_ankle")
        frames[0]["landmarks"]["left_knee"] = [1.2, 0.5, 0.99]
        result = self.build(frames)
        self.assertEqual(result["joint_visibility_rate"]["right_ankle"], 0.25)
        self.assertEqual(result["joint_visibility_rate"]["left_knee"], 0.75)
        self.assertIn("right_ankle", result["low_visibility_joints"])
        self.assertEqual(result["status"], "usable_with_caution_joint_visibility")

    def test_multiple_critical_joints_with_very_low_visibility_recommend_retake(self):
        frames = [self.full_frame() for _ in range(5)]
        for frame in frames:
            for name in ("left_ankle", "right_ankle", "left_foot_index", "right_foot_index"):
                frame["landmarks"].pop(name)
        result = self.build(frames)
        self.assertEqual(result["status"], "retake_recommended_joint_visibility")
        self.assertIn("足先", result["guidance"])

    def test_nonfinite_and_boolean_sizes_or_metrics_are_not_counted(self):
        frames = [self.full_frame(), self.full_frame(), self.full_frame()]
        frames[0]["person_height_ratio"] = float("nan")
        frames[1]["person_height_ratio"] = True
        frames[0]["right_knee_angle_deg"] = float("inf")
        frames[1]["right_knee_angle_deg"] = True
        result = self.build(frames)
        self.assertEqual(result["valid_person_size_samples"], 1)
        self.assertEqual(result["metric_sample_coverage"]["right_knee"]["measured_samples"], 1)
        self.assertEqual(result["status"], "insufficient_samples")

    def test_malformed_landmark_containers_are_treated_as_unobserved(self):
        result = self.build([
            {"person_height_ratio": 0.6, "landmarks": None},
            {"person_height_ratio": 0.6, "landmarks": []},
            {"person_height_ratio": 0.6, "landmarks": "invalid"},
        ])
        self.assertEqual(result["joint_visibility_rate"]["right_knee"], 0.0)
        self.assertIn("right_knee", result["low_visibility_joints"])

    def test_non_list_frame_input_is_treated_as_empty(self):
        result = self.build(None)
        self.assertEqual(result["sampled_pose_frames"], 0)
        self.assertIsNone(result["joint_visibility_rate"]["right_knee"])

    def test_malformed_frame_entries_remain_in_visibility_denominator(self):
        valid_frame = {
            "person_height_ratio": 0.6,
            "landmarks": {"right_knee": [0.5, 0.5, 0.9]},
            "right_knee_angle_deg": 170.0,
        }
        result = self.build([valid_frame, "malformed-frame", valid_frame, valid_frame])
        self.assertEqual(result["sampled_pose_frames"], 4)
        self.assertEqual(result["joint_visibility_rate"]["right_knee"], 0.75)
        self.assertEqual(result["metric_sample_coverage"]["right_knee"]["coverage_rate"], 0.75)

    def test_empty_frames_preserve_unknown_visibility_and_coverage(self):
        result = self.build([])
        self.assertIsNone(result["joint_visibility_rate"]["right_knee"])
        self.assertIsNone(result["metric_sample_coverage"]["right_knee"]["coverage_rate"])
        self.assertEqual(result["status"], "insufficient_samples")


if __name__ == "__main__":
    unittest.main()
