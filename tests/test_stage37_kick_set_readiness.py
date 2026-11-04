import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage37KickSetReadinessTests(unittest.TestCase):
    def test_readiness_tracks_five_views_and_five_phases(self):
        self.assertIn("function renderKickSetReadiness(records,officialAngles)", HTML)
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("['" + key + "'", HTML)
        self.assertIn("const phaseTotal=officialAngles.length*phaseDefs.length", HTML)

    def test_only_manual_phase_confirmation_counts(self):
        self.assertIn("p?.confirmedBy!=='parent_manual_review'", HTML)
        self.assertIn("p.status==='確認済み'&&Number.isFinite(p.timeSeconds)", HTML)
        self.assertIn("映像で確認できず", HTML)

    def test_metadata_completeness_uses_latest_record_per_view(self):
        self.assertIn("latestByAngle.set(angle,matches[matches.length-1])", HTML)
        self.assertIn("['kind','foot','cameraDistance','framing']", HTML)
        self.assertIn("metadataComplete+'/'+metadataTotal", HTML)

    def test_next_actions_cover_missing_views_pending_phases_and_metadata(self):
        for label in ("未撮影視点を追加", "未確認節目を手動確認", "撮影条件の未記録を入力"):
            self.assertIn(label, HTML)

    def test_readiness_is_not_a_technical_skill_score(self):
        self.assertIn("キック技術・フォームの良し悪し・成長度を点数化したものではありません", HTML)

    def test_readiness_is_integrated_in_same_kick_review(self):
        self.assertIn("renderKickSetReadiness(records,officialAngles)", HTML)
        self.assertIn("renderKickSetConsistency(allGroupRecords,records,latest)", HTML)


if __name__ == "__main__":
    unittest.main()
