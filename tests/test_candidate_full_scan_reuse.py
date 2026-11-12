import ast
import math
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODES = [
    next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    for name in ("associate_person_tracks", "summarize_candidate_from_full_scan")
]


class TestVector(tuple):
    def __sub__(self, other):
        return TestVector(a - b for a, b in zip(self, other))


def euclidean_norm(values):
    return math.sqrt(sum(value * value for value in values))


# Minimal NumPy-compatible vector operations used by these two functions.
test_np = types.SimpleNamespace(
    array=lambda values: TestVector(values),
    norm=euclidean_norm,
    linalg=types.SimpleNamespace(norm=euclidean_norm),
    isfinite=math.isfinite,
)
NS = {"np": test_np}
exec(compile(ast.Module(body=NODES, type_ignores=[]), "<candidate-reuse>", "exec"), NS)
summarize = NS["summarize_candidate_from_full_scan"]


class CandidateFullScanReuseTests(unittest.TestCase):
    @staticmethod
    def person(x=0.1, number=None):
        return {
            "person_index": 0,
            "bbox": [x, 0.1, x + 0.1, 0.8],
            "jersey_ocr_candidates": ([{"number": number}] if number else []),
        }

    def test_reuses_only_frames_inside_candidate_clip_window(self):
        frames = [
            {"time_seconds": 5.5, "detected_people": [self.person()]},
            {"time_seconds": 6.0, "detected_people": [self.person(number="10")]},
            {"time_seconds": 6.5, "detected_people": [self.person(0.105, "10")]},
            {"time_seconds": 7.0, "detected_people": [self.person(0.11)]},
            {"time_seconds": 14.1, "detected_people": [self.person()]},
        ]
        result = summarize({
            "duration_seconds": 20,
            "sampling_interval_seconds": 0.5,
            "frames": frames,
        }, center_time=10.0)
        self.assertTrue(result["reused_full_scan"])
        self.assertEqual(result["sampled_frames"], 3)
        self.assertEqual(result["sampling_rate_fps"], 2.0)
        self.assertEqual(result["jersey_candidate_detection_counts"], {"10": 2})
        self.assertEqual(result["track_summary"]["provisional_track_count"], 1)
        self.assertEqual(result["track_summary"]["tracks"][0]["sample_count"], 3)

    def test_supports_multiple_people_and_ignores_malformed_frames(self):
        frames = [
            "bad-frame",
            {"time_seconds": 8, "detected_people": [
                self.person(0.1), self.person(0.7)
            ]},
            {"time_seconds": 8.5, "detected_people": [
                self.person(0.11), self.person(0.69)
            ]},
        ]
        result = summarize({
            "duration_seconds": 20,
            "sampling_interval_seconds": 0.5,
            "frames": frames,
        }, center_time=10)
        self.assertEqual(result["sampled_frames"], 2)
        self.assertEqual(result["max_people_in_one_frame"], 2)
        self.assertEqual(result["track_summary"]["provisional_track_count"], 2)

    def test_invalid_input_returns_empty_safe_summary(self):
        self.assertEqual(summarize(None, 10)["sampled_frames"], 0)
        self.assertEqual(summarize({"frames": []}, float("nan"))["sampled_frames"], 0)

    def test_source_scan_frames_are_not_mutated(self):
        source_person = self.person(number="74")
        source_frames = [{"time_seconds": 10, "detected_people": [source_person]}]
        summarize({
            "duration_seconds": 20,
            "sampling_interval_seconds": 0.5,
            "frames": source_frames,
        }, 10)
        self.assertNotIn("track_id", source_person)


if __name__ == "__main__":
    unittest.main()
