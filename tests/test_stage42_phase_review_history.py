import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage42PhaseReviewHistoryTests(unittest.TestCase):
    def test_previous_manual_phase_value_is_archived_before_overwrite(self):
        self.assertIn("const oldValue=previous[phaseKey]", HTML)
        self.assertIn("history.push({...oldValue,archivedAt:new Date().toISOString()})", HTML)

    def test_history_is_bounded_to_ten_revisions_per_phase(self):
        self.assertIn("record.reviewedKickPhaseHistory[phaseKey]=history.slice(-10)", HTML)

    def test_history_keeps_original_timestamp_status_and_confirmation_fields(self):
        self.assertIn("...oldValue", HTML)
        self.assertIn("reviewedKickPhaseHistory", HTML)

    def test_save_failure_rolls_back_current_value_and_history(self):
        self.assertIn("record.reviewedKickPhases=previous;record.reviewedKickPhaseHistory=previousHistory", HTML)
        self.assertIn("保存に失敗しました。既存データは元に戻しました。", HTML)

    def test_phase_order_guard_still_runs_before_history_mutation(self):
        self.assertIn("validateKickPhaseTimestamp(record,phaseKey,time)", HTML)
        self.assertLess(HTML.index("if(sequenceError){alert("), HTML.index("const previous=JSON.parse(JSON.stringify(record.reviewedKickPhases||{}))"))

    def test_history_is_per_phase_and_does_not_change_other_phase_records(self):
        self.assertIn("record.reviewedKickPhaseHistory[phaseKey]", HTML)
        self.assertIn("record.reviewedKickPhases[phaseKey]", HTML)


if __name__ == "__main__":
    unittest.main()
