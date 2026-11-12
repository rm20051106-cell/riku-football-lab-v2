import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


class Stage69MovementCandidateWindowTests(unittest.TestCase):
    def test_support_count_uses_bisect_on_time_sorted_samples(self):
        tree = ast.parse(SOURCE)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_movement_candidates"
        )
        source = ast.get_source_segment(SOURCE, function)
        self.assertIn("scored_times = [item[\"time_seconds\"] for item in scored]", source)
        self.assertIn("bisect.bisect_left", source)
        self.assertIn("bisect.bisect_right", source)

    def test_original_neighbor_distance_and_score_predicates_are_preserved(self):
        tree = ast.parse(SOURCE)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_movement_candidates"
        )
        source = ast.get_source_segment(SOURCE, function)
        self.assertIn("other is not item", source)
        self.assertIn("0 < abs(item_time - other[\"time_seconds\"]) <= max_adjacent_gap", source)
        self.assertIn("other[\"score\"] >= item[\"score\"] * 0.35", source)

    def test_candidate_threshold_spacing_and_output_contract_are_unchanged(self):
        tree = ast.parse(SOURCE)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_movement_candidates"
        )
        source = ast.get_source_segment(SOURCE, function)
        for unchanged in (
            "int((len(values) - 1) * 0.75)",
            'item["score"] > 0.015',
            'abs(item["time_seconds"] - old["time_seconds"]) >= 10',
            '"temporal_support_samples"',
            '"is_football_action_confirmed": False',
        ):
            self.assertIn(unchanged, source)


if __name__ == "__main__":
    unittest.main()
