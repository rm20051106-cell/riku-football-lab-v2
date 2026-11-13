import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE_SOURCE = (ROOT / "backend" / "profile_match_video.py").read_text(encoding="utf-8")


def load_comparison_builder():
    tree = ast.parse(PROFILE_SOURCE)
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_number", "build_comparison_report"}
    ]
    namespace = {}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), "<comparison_report>", "exec"), namespace)
    return namespace["build_comparison_report"]


build_comparison_report = load_comparison_builder()


def run(max_poses, wall, sampled, detected, rate, people, interval=0.5):
    return {
        "max_poses": max_poses,
        "wall_clock_seconds": wall,
        "sampling_interval_seconds": interval,
        "sampled_pose_frames": sampled,
        "video_scan_quality": {
            "pose_detected_frames": detected,
            "pose_detection_rate": rate,
        },
        "person_detection_summary": {
            "frames_with_people": detected,
            "average_people_per_sample": people / sampled if sampled else None,
            "max_people_in_one_frame": max_poses,
        },
        "scan_timing": {
            "pose_inference_seconds": wall * 0.6,
            "pose_person_count": people,
        },
    }


class PoseCountComparisonReportTests(unittest.TestCase):
    def test_compares_detection_counts_rate_samples_and_processing_time(self):
        report = build_comparison_report([
            run(8, 100.0, 200, 160, 0.8, 300),
            run(4, 82.0, 200, 150, 0.75, 240),
        ])

        baseline, capped = report["runs"]
        comparison = report["comparison"]
        self.assertEqual([baseline["max_poses"], capped["max_poses"]], [8, 4])
        self.assertEqual([baseline["sampled_pose_frames"], capped["sampled_pose_frames"]], [200, 200])
        self.assertEqual([baseline["pose_detected_frames"], capped["pose_detected_frames"]], [160, 150])
        self.assertEqual([baseline["missed_pose_frames"], capped["missed_pose_frames"]], [40, 50])
        self.assertEqual([baseline["pose_detection_rate"], capped["pose_detection_rate"]], [0.8, 0.75])
        self.assertEqual([baseline["total_person_detections"], capped["total_person_detections"]], [300, 240])
        self.assertEqual(comparison["wall_clock_seconds_saved"], 18.0)
        self.assertEqual(comparison["wall_clock_reduction_percent"], 18.0)
        self.assertTrue(comparison["same_sample_count"])
        self.assertTrue(comparison["same_sampling_interval"])
        self.assertEqual(comparison["pose_detection_rate_delta"], -0.05)
        self.assertEqual(comparison["total_person_detections_delta"], -60)

    def test_derives_detection_rate_when_quality_rate_is_missing(self):
        first = run(8, 10.0, 20, 15, 0.75, 25)
        second = run(4, 8.0, 20, 10, 0.5, 18)
        for item in (first, second):
            item["video_scan_quality"].pop("pose_detection_rate")

        report = build_comparison_report([first, second])
        self.assertEqual(report["runs"][0]["pose_detection_rate"], 0.75)
        self.assertEqual(report["runs"][1]["pose_detection_rate"], 0.5)
        self.assertEqual(report["comparison"]["pose_detection_rate_delta"], -0.25)

    def test_zero_samples_and_missing_times_do_not_divide_by_zero(self):
        report = build_comparison_report([
            {"max_poses": 8, "sampled_pose_frames": 0},
            {"max_poses": 4, "sampled_pose_frames": 0},
        ])
        self.assertEqual(report["runs"][0]["pose_detection_rate"], None)
        self.assertEqual(report["runs"][1]["pose_detection_rate"], None)
        self.assertIsNone(report["comparison"]["wall_clock_seconds_saved"])
        self.assertIsNone(report["comparison"]["wall_clock_reduction_percent"])
        self.assertIsNone(report["comparison"]["pose_detection_rate_delta"])
        self.assertTrue(report["comparison"]["same_sample_count"])

    def test_comparison_keeps_sampling_mismatch_visible(self):
        first = run(8, 12.0, 24, 18, 0.75, 30)
        second = run(4, 9.0, 20, 14, 0.7, 22, interval=0.6)
        comparison = build_comparison_report([first, second])["comparison"]
        self.assertFalse(comparison["same_sample_count"])
        self.assertFalse(comparison["same_sampling_interval"])

    def test_cli_default_and_backend_default_remain_eight(self):
        parser_line = next(
            line for line in PROFILE_SOURCE.splitlines()
            if 'parser.add_argument("--max-poses"' in line
        )
        self.assertIn("default=8", parser_line)
        backend = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(backend)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "process_match_video"
        )
        self.assertEqual(function.args.defaults[-1].value, 8)



class PoseCountComparisonFixtureTests(unittest.TestCase):
    @staticmethod
    def fixture(max_poses, wall, samples, detected, people, interval=0.5):
        return {
            "fixture_only": True,
            "max_poses": max_poses,
            "wall_clock_seconds": wall,
            "sampling_interval_seconds": interval,
            "sampled_pose_frames": samples,
            "video_scan_quality": {"pose_detected_frames": detected},
            "person_detection_summary": {
                "frames_with_people": detected,
                "average_people_per_sample": people / samples if samples else None,
                "max_people_in_one_frame": min(max_poses, 8),
            },
            "scan_timing": {"pose_inference_seconds": wall * 0.6, "pose_person_count": people},
        }

    def test_fixture_compares_all_requested_metrics_without_claiming_real_speed(self):
        report = build_comparison_report([
            self.fixture(8, 100.0, 200, 160, 300),
            self.fixture(4, 82.0, 200, 150, 240),
        ])
        self.assertEqual([x["max_poses"] for x in report["runs"]], [8, 4])
        self.assertEqual([x["sampled_pose_frames"] for x in report["runs"]], [200, 200])
        self.assertEqual([x["pose_detected_frames"] for x in report["runs"]], [160, 150])
        self.assertEqual([x["pose_detection_rate"] for x in report["runs"]], [0.8, 0.75])
        self.assertEqual([x["total_person_detections"] for x in report["runs"]], [300, 240])
        self.assertEqual(report["comparison"]["wall_clock_seconds_saved"], 18.0)
        self.assertEqual(report["comparison"]["pose_detected_frames_delta"], -10)
        self.assertTrue(report["comparison"]["timing_is_synthetic"])
        self.assertIn("not MediaPipe", report["measurement_note"])

    def test_invalid_counts_are_clamped_and_missing_metrics_stay_null(self):
        report = build_comparison_report([
            {"fixture_only": True, "max_poses": 8, "sampled_pose_frames": 5,
             "video_scan_quality": {"pose_detected_frames": 9, "pose_detection_rate": 1.4}},
            {"fixture_only": True, "max_poses": 4, "sampled_pose_frames": 0},
        ])
        first, second = report["runs"]
        self.assertEqual(first["pose_detected_frames"], 5)
        self.assertEqual(first["missed_pose_frames"], 0)
        self.assertEqual(first["pose_detection_rate"], 1.0)
        self.assertIsNone(second["pose_detection_rate"])
        self.assertIsNone(report["comparison"]["wall_clock_seconds_saved"])
        self.assertIsNone(report["comparison"]["total_person_detections_delta"])

    def test_sampling_mismatch_marks_comparison_not_comparable(self):
        report = build_comparison_report([
            self.fixture(8, 10, 20, 15, 25, 0.5),
            self.fixture(4, 8, 19, 13, 21, 0.6),
        ])
        self.assertFalse(report["comparison"]["same_sample_count"])
        self.assertFalse(report["comparison"]["same_sampling_interval"])
        self.assertFalse(report["comparison"]["comparable_sampling"])


if __name__ == "__main__":
    unittest.main()
