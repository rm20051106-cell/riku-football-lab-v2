import ast
import math
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
SW = (ROOT / "sw.js").read_text(encoding="utf-8")


class Stage64PoseInferenceLatencyTests(unittest.TestCase):
    def test_backend_records_per_sample_latency_percentiles(self):
        tree = ast.parse(BACKEND)
        source = BACKEND
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

    def test_metrics_are_promoted_into_completed_job_api_result(self):
        run_job = BACKEND[BACKEND.index("def run_match_job("):BACKEND.index("def resume_interrupted_match_jobs(")]
        self.assertIn('"pose_scan_breakdown": summary.get("scan_timing", {})', run_job)
        for key in ("pose_inference_sample_count", "pose_inference_p50_seconds", "pose_inference_p95_seconds", "pose_inference_max_seconds"):
            self.assertIn('"' + key + '"', run_job)
        endpoint = BACKEND[BACKEND.index('@app.get("/analyze/jobs/{job_id}")'):BACKEND.index('@app.post("/analyze/jobs/{job_id}/highlights")')]
        self.assertIn('payload["result"] = job["result"]', endpoint)

    def test_frontend_displays_count_and_all_latency_percentiles(self):
        for key in (
            "pose_inference_sample_count",
            "pose_inference_p50_seconds",
            "pose_inference_p95_seconds",
            "pose_inference_max_seconds",
        ):
            self.assertIn(key, HTML)
        self.assertIn("perf?.pose_inference_sample_count??scanPerf.pose_inference_sample_count", HTML)
        self.assertIn("sm.scan_timing||{}", HTML)
        self.assertIn("測定 ", HTML)
        self.assertIn("中央値 ", HTML)
        self.assertIn("95%点 ", HTML)
        self.assertIn("const j=status.result||{},sm=j.summary||{};", HTML)
        self.assertIn("const perf=sm.performance_metrics||null;", HTML)
        self.assertIn("const scanPerf=perf?.pose_scan_breakdown||sm.scan_timing||{};", HTML)

    def test_service_worker_cache_is_bumped_to_refresh_stale_app_shell(self):
        self.assertIn('riku-football-lab-shell-v5', SW)
        self.assertNotIn('riku-football-lab-shell-v4', SW)


    def test_pose_postprocess_caches_landmark_reads_without_changing_geometry(self):
        tree = ast.parse(BACKEND)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "analyze_task_pose")
        indices = {
            "LEFT_SHOULDER": 11, "RIGHT_SHOULDER": 12,
            "LEFT_HIP": 23, "RIGHT_HIP": 24,
            "LEFT_KNEE": 25, "RIGHT_KNEE": 26,
            "LEFT_ANKLE": 27, "RIGHT_ANKLE": 28,
            "LEFT_HEEL": 29, "RIGHT_HEEL": 30,
            "LEFT_FOOT_INDEX": 31, "RIGHT_FOOT_INDEX": 32,
        }

        class FakeLandmark:
            def __init__(self, index):
                self._x = index / 100
                self._y = index / 200
                self._visibility = 1.0
                self.reads = {"x": 0, "y": 0, "visibility": 0}

            @property
            def x(self):
                self.reads["x"] += 1
                return self._x

            @property
            def y(self):
                self.reads["y"] += 1
                return self._y

            @property
            def visibility(self):
                self.reads["visibility"] += 1
                return self._visibility

        class FakePoseLandmark:
            def __init__(self):
                self.lookups = {}

            def __getitem__(self, name):
                self.lookups[name] = self.lookups.get(name, 0) + 1
                return types.SimpleNamespace(value=indices[name])

        landmarks = [FakeLandmark(index) for index in range(33)]
        pose_landmark = FakePoseLandmark()

        def fake_angle(a, b, c, width, height):
            return round(sum(a) + sum(b) + sum(c) + width / 1000 + height / 1000, 1)

        namespace = {
            "mp_pose": types.SimpleNamespace(PoseLandmark=pose_landmark),
            "np": types.SimpleNamespace(degrees=math.degrees, arctan2=math.atan2),
            "angle": fake_angle,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<analyze_task_pose>", "exec"), namespace)
        result = namespace["analyze_task_pose"](landmarks, 640, 360)

        self.assertEqual(result["visible_landmarks"], 33)
        self.assertEqual(result["left_knee_angle_deg"], 2.1)
        self.assertEqual(result["right_knee_angle_deg"], 2.2)
        self.assertEqual(result["left_hip_angle_deg"], 1.9)
        self.assertEqual(result["right_hip_angle_deg"], 1.9)
        self.assertAlmostEqual(result["trunk_lean_image_angle_deg"], 74.3, places=1)
        self.assertEqual(result["bbox"], [0.0, 0.0, 0.32, 0.16])
        self.assertEqual(result["landmarks"]["left_ankle"], [0.27, 0.135, 1.0])
        self.assertEqual(pose_landmark.lookups, {name: 1 for name in indices})
        for landmark in landmarks:
            self.assertEqual(landmark.reads, {"x": 1, "y": 1, "visibility": 1})


if __name__ == "__main__":
    unittest.main()
