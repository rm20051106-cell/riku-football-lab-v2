import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage34FiveViewEvidenceMatrixTests(unittest.TestCase):
    def test_matrix_uses_the_five_standard_views_in_order(self):
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn("'" + angle + "'", HTML)
        self.assertIn("function renderFiveViewPhaseEvidenceMatrix(records,officialAngles)", HTML)

    def test_matrix_contains_the_five_manual_phase_keys(self):
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("['" + key + "'", HTML)

    def test_each_angle_uses_its_latest_record_only(self):
        self.assertIn("latestByAngle.set(angle,matches[matches.length-1])", HTML)
        self.assertIn("matches[matches.length-1]", HTML)

    def test_manual_confirmed_timestamp_is_required_for_confirmed_cell(self):
        self.assertIn("p.confirmedBy!=='parent_manual_review'", HTML)
        self.assertIn("p.status==='確認済み'", HTML)
        self.assertIn("Number.isFinite(p.timeSeconds)", HTML)

    def test_not_visible_and_unconfirmed_are_distinct(self):
        self.assertIn("映像で確認できず", HTML)
        self.assertIn("未確認", HTML)
        self.assertIn("動画なし", HTML)

    def test_no_cross_view_timestamp_sync_or_evidence_fill(self):
        self.assertIn("別動画・別視点間で時刻を同期したり、未確認を他の視点から補完したりしません", HTML)

    def test_matrix_is_integrated_into_same_kick_multi_angle_review(self):
        self.assertIn("renderFiveViewPhaseEvidenceMatrix(records,officialAngles)", HTML)
        self.assertIn("const groupId=String(latest.kickGroupId)", HTML)


if __name__ == "__main__":
    unittest.main()
