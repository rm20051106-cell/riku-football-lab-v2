import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage32ManualKickPhaseReviewTests(unittest.TestCase):
    def test_five_phases_have_separate_manual_timestamp_inputs(self):
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("['" + key + "'", HTML)
            self.assertIn("kick-phase-time-", HTML)
            self.assertIn("kick-phase-status-", HTML)

    def test_only_parent_manual_review_is_saved_as_confirmed_evidence(self):
        self.assertIn("confirmedBy:'parent_manual_review'", HTML)
        self.assertIn("status==='未確認'", HTML)
        self.assertIn("確認済み", HTML)
        self.assertIn("映像で確認できず", HTML)

    def test_manual_review_is_persisted_and_rerendered(self):
        self.assertIn("function saveKickPhaseReview(recordId,phaseKey)", HTML)
        self.assertIn("record.reviewedKickPhases[phaseKey]", HTML)
        self.assertIn("if(!persist())", HTML)
        self.assertIn("renderAll();", HTML)

    def test_multi_angle_view_shows_manual_phase_evidence_by_camera(self):
        self.assertIn("動作節目の角度別・手動時刻一覧", HTML)
        self.assertIn("r.reviewedKickPhases?.[key]", HTML)
        self.assertIn("手動", HTML)

    def test_ai_candidates_are_not_overwritten_by_manual_times(self):
        self.assertIn("kickPhaseCandidates:sm.kick_phase_candidates||null", HTML)
        self.assertIn("reviewedKickPhases", HTML)
        self.assertIn("AI候補時刻とは別データ", HTML)


if __name__ == "__main__":
    unittest.main()
