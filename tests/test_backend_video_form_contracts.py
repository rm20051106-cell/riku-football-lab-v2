import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function_node(name):
    return next(node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def loaded_names(node):
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}


class BackendVideoFormAnalysisContracts(unittest.TestCase):
    def test_form_phase_candidates_are_created_in_form_video_pipeline(self):
        node = function_node("process_video")
        assignments = [
            item for item in ast.walk(node)
            if isinstance(item, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "kick_phase_candidates" for target in item.targets)
        ]
        self.assertTrue(assignments, "form pipeline must build kick phase candidates")
        self.assertIn("build_kick_phase_candidates", loaded_names(node))
        self.assertIn('summary["kick_phase_candidates"] = kick_phase_candidates', SOURCE)

    def test_match_video_pipeline_does_not_reference_undefined_mode(self):
        node = function_node("process_match_video")
        self.assertNotIn("mode", loaded_names(node), "match-only pipeline must not read an undefined mode variable")

    def test_form_phase_labels_remain_candidates_not_confirmed_events(self):
        phase_builder = function_node("build_kick_phase_candidates")
        source = ast.get_source_segment(SOURCE, phase_builder)
        self.assertIn("manual_review_required", source)
        self.assertIn("candidate_only", source)
        self.assertIn("インパクト", source)
        self.assertIn("軸足接地", source)

    def test_invisible_joint_measurements_are_not_fabricated(self):
        self.assertIn('"insufficient_visibility"', SOURCE)
        self.assertIn('"left_knee_angle_deg": left_knee', SOURCE)
        self.assertIn('"right_knee_angle_deg": right_knee', SOURCE)
        self.assertIn('"not_inferred": True', SOURCE)


if __name__ == "__main__":
    unittest.main()
