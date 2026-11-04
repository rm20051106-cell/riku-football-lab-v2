import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def capture_quality_function():
    return next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                and node.name == "build_form_capture_quality")


class Stage51CaptureVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = capture_quality_function()
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {}
        exec(compile(module, "<capture-quality>", "exec"), namespace)
        cls.build = staticmethod(namespace["build_form_capture_quality"])

    def test_missing_joint_entries_reduce_visibility_rate(self):
        frames = [
            {"person_height_ratio": 0.6, "landmarks": {"right_knee": [0.5, 0.5, 0.9]}},
            {"person_height_ratio": 0.6, "landmarks": {}},
            {"person_height_ratio": 0.6, "landmarks": {"right_knee": [0.5, 0.5, 0.8]}},
            {"person_height_ratio": 0.6, "landmarks": {}},
        ]
        result = self.build(frames)
        self.assertEqual(result["joint_visibility_rate"]["right_knee"], 0.5)

    def test_missing_joint_in_every_frame_is_zero_not_unknown(self):
        frames = [
            {"person_height_ratio": 0.6, "landmarks": {}},
            {"person_height_ratio": 0.6, "landmarks": {}},
            {"person_height_ratio": 0.6, "landmarks": {}},
        ]
        result = self.build(frames)
        self.assertEqual(result["joint_visibility_rate"]["left_ankle"], 0.0)

    def test_visible_joint_in_every_frame_is_full_coverage(self):
        frames = [
            {"person_height_ratio": 0.6, "landmarks": {"left_ankle": [0.4, 0.8, 0.5]}},
            {"person_height_ratio": 0.6, "landmarks": {"left_ankle": [0.4, 0.8, 0.99]}},
            {"person_height_ratio": 0.6, "landmarks": {"left_ankle": [0.4, 0.8, 0.7]}},
        ]
        result = self.build(frames)
        self.assertEqual(result["joint_visibility_rate"]["left_ankle"], 1.0)

    def test_empty_frames_keep_visibility_unknown(self):
        result = self.build([])
        self.assertIsNone(result["joint_visibility_rate"]["right_knee"])
        self.assertEqual(result["status"], "insufficient_samples")


if __name__ == "__main__":
    unittest.main()
