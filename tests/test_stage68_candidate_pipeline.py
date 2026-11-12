import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


class Stage68CandidatePipelineTests(unittest.TestCase):
    def test_candidate_pipeline_exposes_stage_and_per_clip_timings(self):
        run_job = BACKEND[
            BACKEND.index("def run_match_job("):
            BACKEND.index("def resume_interrupted_match_jobs(")
        ]
        for key in (
            "candidate_selection_seconds",
            "candidate_frame_index_seconds",
            "clip_extraction_seconds",
            "clip_extraction_per_clip",
            "candidate_track_summary_per_candidate",
            "candidate_frame_filter_seconds",
            "candidate_track_association_seconds",
        ):
            self.assertIn('"' + key + '"', run_job)

    def test_clip_extraction_records_each_ffmpeg_call_duration_and_size(self):
        tree = ast.parse(BACKEND)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "extract_candidate_clips"
        )
        source = ast.get_source_segment(BACKEND, function)
        self.assertIn("time.perf_counter()", source)
        self.assertIn('"elapsed_seconds"', source)
        self.assertIn('"output_size_bytes"', source)
        self.assertIn('"succeeded"', source)

    def test_indexed_candidate_summary_uses_binary_search_and_same_association(self):
        tree = ast.parse(BACKEND)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "summarize_candidate_from_full_scan"
        )
        source = ast.get_source_segment(BACKEND, function)
        self.assertIn("bisect.bisect_left", BACKEND)
        self.assertIn("bisect.bisect_right", BACKEND)
        self.assertIn("frame_index", source)
        self.assertIn("associate_person_tracks(", source)
        self.assertNotIn("detect_for_video(", source)

    def test_time_index_falls_back_for_non_monotonic_frame_times(self):
        tree = ast.parse(BACKEND)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_candidate_frame_time_index"
        )
        source = ast.get_source_segment(BACKEND, function)
        self.assertIn("timestamp < previous_time", source)
        self.assertIn("return None", source)


if __name__ == "__main__":
    unittest.main()
