import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
SW = (ROOT / "sw.js").read_text(encoding="utf-8")


class Stage64PoseInferenceLatencyTests(unittest.TestCase):
    def test_backend_records_per_sample_latency_percentiles(self):
        tree = ast.parse(BACKEND)
        source = ast.get_source_segment(BACKEND, tree)
        for key in (
            "pose_inference_sample_count",
            "pose_inference_p50_seconds",
            "pose_inference_p95_seconds",
            "pose_inference_max_seconds",
        ):
            self.assertIn(key, source)
        self.assertIn("pose_inference_latencies.append(inference_elapsed)", source)
        self.assertIn("np.percentile(pose_inference_latencies, 50)", source)
        self.assertIn("np.percentile(pose_inference_latencies, 95)", source)

    def test_percentiles_keep_four_decimal_precision(self):
        self.assertIn("round(value, 4)", BACKEND)
        self.assertIn('"pose_inference_p50_seconds"', BACKEND)
        self.assertIn('"pose_inference_p95_seconds"', BACKEND)
        self.assertIn('"pose_inference_max_seconds"', BACKEND)

    def test_frontend_displays_count_and_all_latency_percentiles(self):
        for key in (
            "pose_inference_sample_count",
            "pose_inference_p50_seconds",
            "pose_inference_p95_seconds",
            "pose_inference_max_seconds",
        ):
            self.assertIn(key, HTML)
        self.assertIn("測定 ", HTML)
        self.assertIn("中央値 ", HTML)
        self.assertIn("95%点 ", HTML)

    def test_service_worker_cache_is_bumped_to_refresh_stale_app_shell(self):
        self.assertIn('riku-football-lab-shell-v5', SW)
        self.assertNotIn('riku-football-lab-shell-v4', SW)


if __name__ == "__main__":
    unittest.main()
