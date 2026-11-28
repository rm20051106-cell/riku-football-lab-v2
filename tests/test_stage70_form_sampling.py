import ast
import math
import pathlib
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BACKEND_TREE = ast.parse(BACKEND_SOURCE)
HTML_SOURCE = (ROOT / "index.html").read_text(encoding="utf-8")


def function_node(name):
    return next(
        node for node in BACKEND_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def load_sampling_helpers():
    nodes = [function_node("build_form_sampling_plan"),
             function_node("advance_form_sampling_cursor")]
    namespace = {
        "np": SimpleNamespace(isfinite=math.isfinite),
        "FORM_SAMPLE_RATE": 4.0,
        "FORM_MAX_SAMPLES": 240,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, "<stage70-form-sampling>", "exec"), namespace)
    return namespace


class Stage70FormSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers = load_sampling_helpers()
        cls.plan = staticmethod(helpers["build_form_sampling_plan"])
        cls.advance = staticmethod(helpers["advance_form_sampling_cursor"])

    def sampled_indices(self, fps, total_frames):
        plan = self.plan(fps)
        cursor = 0.0
        indices = []
        for frame_index in range(total_frames):
            due, cursor = self.advance(frame_index, cursor, plan["frame_interval"])
            if due and len(indices) < plan["sample_limit"]:
                indices.append(frame_index)
        return plan, indices

    def test_30fps_sixty_second_video_keeps_four_fps_across_full_duration(self):
        plan, indices = self.sampled_indices(30.0, 1800)
        self.assertEqual(plan["sampling_rate_fps"], 4.0)
        self.assertEqual(plan["sampling_interval_seconds"], 0.25)
        self.assertEqual(plan["sample_limit"], 240)
        self.assertEqual(len(indices), 240)
        self.assertEqual(indices[0], 0)
        self.assertGreater(indices[-1] / 30.0, 59.5)
        gaps = [right - left for left, right in zip(indices, indices[1:])]
        self.assertEqual(set(gaps), {7, 8})

    def test_60fps_and_24fps_use_fractional_cadence_without_duplicate_frames(self):
        for fps, expected_gap in ((60.0, 15), (24.0, 6)):
            with self.subTest(fps=fps):
                plan, indices = self.sampled_indices(fps, int(fps * 60))
                self.assertEqual(plan["sampling_rate_fps"], 4.0)
                self.assertEqual(len(indices), 240)
                self.assertEqual(set(right - left for left, right in zip(indices, indices[1:])),
                                 {expected_gap})

    def test_source_below_target_rate_is_never_oversampled(self):
        plan, indices = self.sampled_indices(2.0, 120)
        self.assertEqual(plan["sampling_rate_fps"], 2.0)
        self.assertEqual(plan["sampling_interval_seconds"], 0.5)
        self.assertEqual(indices, list(range(120)))

    def test_invalid_source_rate_uses_conservative_one_frame_per_second_fallback(self):
        for fps in (0, -1, float("nan"), float("inf"), None, "invalid"):
            with self.subTest(fps=fps):
                plan = self.plan(fps)
                self.assertEqual(plan["sampling_rate_fps"], 1.0)
                self.assertEqual(plan["sampling_interval_seconds"], 1.0)
                self.assertEqual(plan["frame_interval"], 1.0)

    def test_form_pipeline_uses_form_plan_but_match_pipeline_keeps_match_constants(self):
        node = function_node("process_video")
        source = ast.get_source_segment(BACKEND_SOURCE, node)
        self.assertIn('form_sampling_plan = build_form_sampling_plan(fps)', source)
        self.assertIn('max_samples = form_sampling_plan["sample_limit"]', source)
        self.assertIn('target_sample_rate = MATCH_SAMPLE_RATE', source)
        self.assertIn('max_samples = MATCH_MAX_SAMPLES', source)
        self.assertIn('advance_form_sampling_cursor(', source)

    def test_saved_detailed_timeline_expands_without_changing_compact_timeline(self):
        self.assertIn("const timeline=rawFrames.filter((_,i)=>i%stride===0).slice(0,8)", HTML_SOURCE)
        self.assertIn("const phaseTimeline=rawFrames.slice(0,240)", HTML_SOURCE)
        self.assertNotIn("const phaseTimeline=rawFrames.slice(0,120)", HTML_SOURCE)

    def test_legacy_sampling_and_existing_phase_candidate_contracts_remain_compatible(self):
        self.assertIn('"sampling_interval_seconds": round(actual_interval, 3)', BACKEND_SOURCE)
        self.assertIn('"sampling_rate_fps": round(1 / actual_interval, 2)', BACKEND_SOURCE)
        self.assertIn('summary["kick_phase_candidates"] = kick_phase_candidates', BACKEND_SOURCE)
        self.assertIn('"impact", "label": "インパクト", "status": "manual_review_required"', BACKEND_SOURCE)
        self.assertIn("FORM_MAX_SAMPLES = 240", BACKEND_SOURCE)


if __name__ == "__main__":
    unittest.main()
