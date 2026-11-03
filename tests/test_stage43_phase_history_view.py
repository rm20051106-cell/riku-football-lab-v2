import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage43PhaseHistoryViewTests(unittest.TestCase):
    def test_history_is_read_from_per_phase_history_storage(self):
        self.assertIn("const history=record.reviewedKickPhaseHistory||{}", HTML)
        self.assertIn("history[key].slice(-3).reverse()", HTML)

    def test_history_shows_previous_status_time_and_date(self):
        self.assertIn("item.status||'状態不明'", HTML)
        self.assertIn("Number(item.timeSeconds).toFixed(2)+'秒'", HTML)
        self.assertIn("new Date(item.archivedAt).toLocaleString('ja-JP')", HTML)

    def test_history_is_collapsible_and_limited_to_three_displayed_revisions(self):
        self.assertIn("<details style=\"margin-top:7px\"><summary", HTML)
        self.assertIn("手動確認の変更履歴（最新3件／節目）", HTML)
        self.assertIn("slice(-3).reverse()", HTML)

    def test_history_display_does_not_change_current_manual_review(self):
        self.assertIn("const reviewed=record.reviewedKickPhases||{}", HTML)
        self.assertIn("const history=record.reviewedKickPhaseHistory||{}", HTML)
        self.assertIn("過去の手動入力を表示します", HTML)

    def test_history_view_is_integrated_in_each_angle_record(self):
        self.assertIn("renderKickPhaseTimeIntegrity(r)", HTML)


if __name__ == "__main__":
    unittest.main()
