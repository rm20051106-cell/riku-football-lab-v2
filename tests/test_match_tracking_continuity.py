import ast
import math
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "associate_person_tracks")


class TestVector(tuple):
    def __sub__(self, other):
        return TestVector(a - b for a, b in zip(self, other))


def euclidean_norm(values):
    return math.sqrt(sum(value * value for value in values))


test_np = types.SimpleNamespace(
    array=lambda values: TestVector(values),
    norm=euclidean_norm,
)
NS = {"np": test_np}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "<track-continuity>", "exec"), NS)
associate = NS["associate_person_tracks"]


class MatchTrackContinuityTests(unittest.TestCase):
    @staticmethod
    def person(x, number=None):
        return {
            "bbox": [x, 0.1, x + 0.08, 0.8],
            "jersey_ocr_candidates": ([{"number": number}] if number else []),
        }

    def test_motion_prediction_preserves_tracks_when_players_cross(self):
        # A moves right; B moves left. At the final sample, both have moved
        # beyond the old fixed 0.22 center-distance gate from their last boxes.
        frames = [
            {"time_seconds": 0.0, "detected_people": [self.person(0.10), self.person(0.82)]},
            {"time_seconds": 0.5, "detected_people": [self.person(0.30), self.person(0.62)]},
            {"time_seconds": 1.0, "detected_people": [self.person(0.50), self.person(0.42)]},
        ]
        result = associate(frames, max_gap_seconds=2.0)
        a_ids = [frame["detected_people"][0]["track_id"] for frame in frames]
        b_ids = [frame["detected_people"][1]["track_id"] for frame in frames]
        self.assertEqual(a_ids, ["T1", "T1", "T1"])
        self.assertEqual(b_ids, ["T2", "T2", "T2"])
        self.assertEqual(result["provisional_track_count"], 2)
        self.assertEqual([x["sample_count"] for x in result["tracks"]], [3, 3])

    def test_jersey_candidate_remains_supporting_identity_signal(self):
        frames = [
            {"time_seconds": 0.0, "detected_people": [self.person(0.1, "10")]},
            {"time_seconds": 0.5, "detected_people": [self.person(0.12, "10")]},
        ]
        result = associate(frames)
        self.assertEqual(result["tracks"][0]["jersey_number_candidates"], {"10": 2})
        self.assertIn("OCR候補", result["note"])


if __name__ == "__main__":
    unittest.main()
