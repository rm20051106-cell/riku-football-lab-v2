import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage36KickSetConsistencyTests(unittest.TestCase):
    def test_consistency_checks_four_recording_conditions(self):
        for key in ("kind", "foot", "cameraDistance", "framing"):
            self.assertIn("['" + key + "'", HTML)
        self.assertIn("function renderKickSetConsistency(allGroupRecords,selectedRecords,latest)", HTML)

    def test_kind_and_dominant_foot_mismatches_are_excluded(self):
        self.assertIn("(x.kind||'シュート')===(latest.kind||'シュート')", HTML)
        self.assertIn("(x.foot||'右足')===(latest.foot||'右足')", HTML)
        self.assertIn("条件不一致で除外", HTML)

    def test_distance_and_framing_are_warnings_not_silent_overwrites(self):
        self.assertIn("撮影距離に差または未記録があります", HTML)
        self.assertIn("画角に差または未記録があります", HTML)
        self.assertIn("動画や手動確認記録は削除・上書きしません", HTML)

    def test_unrecorded_metadata_is_explicit(self):
        self.assertIn("一部未記録", HTML)
        self.assertIn("未記録", HTML)
        self.assertIn("値なし", HTML)

    def test_consistency_check_is_integrated_into_multi_angle_view(self):
        self.assertIn("renderKickSetConsistency(allGroupRecords,records,latest)", HTML)
        self.assertIn("renderFiveViewCoverageGuidance(records,officialAngles)", HTML)

    def test_mismatched_kind_or_foot_does_not_enter_evidence_set(self):
        self.assertIn("const allGroupRecords=all.filter(x=>x.kickGroupId===latest.kickGroupId)", HTML)
        self.assertIn("const records=allGroupRecords.filter", HTML)


if __name__ == "__main__":
    unittest.main()
