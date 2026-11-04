import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function(name):
    return next(node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)


class Stage56PreferredFootPipelineTests(unittest.TestCase):
    def test_process_video_declares_preferred_foot_with_right_default(self):
        node = function("process_video")
        defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):], node.args.defaults))
        self.assertIn("preferred_foot", defaults)
        self.assertEqual(ast.literal_eval(defaults["preferred_foot"]), "right")

    def test_original_and_converted_video_paths_forward_preferred_foot(self):
        node = function("analyze_upload")
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "process_video"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            keywords = {kw.arg: kw.value for kw in call.keywords}
            self.assertIn("preferred_foot", keywords)
            self.assertIsInstance(keywords["preferred_foot"], ast.Name)
            self.assertEqual(keywords["preferred_foot"].id, "preferred_foot")

    def test_form_endpoint_normalizes_and_passes_selected_foot(self):
        node = function("analyze_form")
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "analyze_upload"]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertIn("preferred_foot", keywords)
        self.assertIsInstance(keywords["preferred_foot"], ast.Name)
        self.assertEqual(keywords["preferred_foot"].id, "normalized_foot")


if __name__ == "__main__":
    unittest.main()
