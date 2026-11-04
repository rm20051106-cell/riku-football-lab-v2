import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage40PhaseTimeSaveGuardTests(unittest.TestCase):
    def test_save_guard_uses_the_five_ordered_phases(self):
        self.assertIn("function validateKickPhaseTimestamp(record,phaseKey,time)", HTML)
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("'" + key + "'", HTML)

    def test_only_other_manually_confirmed_phases_constrain_save(self):
        self.assertIn("other?.confirmedBy!=='parent_manual_review'||other.status!=='確認済み'||!Number.isFinite(other.timeSeconds)", HTML)

    def test_preceding_and_following_phase_order_is_enforced(self):
        self.assertIn("time<=other.timeSeconds", HTML)
        self.assertIn("time>=other.timeSeconds", HTML)
        self.assertIn("前の節目", HTML)
        self.assertIn("次の節目", HTML)

    def test_save_is_blocked_before_mutating_existing_record(self):
        self.assertIn("const sequenceError=validateKickPhaseTimestamp(record,phaseKey,time)", HTML)
        self.assertIn("if(sequenceError){alert(", HTML)
        self.assertLess(HTML.index("if(sequenceError){alert("), HTML.index("const previous=JSON.parse(JSON.stringify(record.reviewedKickPhases||{}))"))

    def test_unobservable_phase_can_still_be_saved_without_a_timestamp(self):
        self.assertIn("status==='確認済み'", HTML)
        self.assertIn("status==='未確認'", HTML)
        self.assertIn("映像で確認できず", HTML)

    def test_existing_data_is_restored_if_persist_fails(self):
        self.assertIn("record.reviewedKickPhases=previous;record.reviewedKickPhaseHistory=previousHistory;alert('保存に失敗しました。既存データは元に戻しました。')", HTML)


if __name__ == "__main__":
    unittest.main()
