import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage38PhaseTimeIntegrityTests(unittest.TestCase):
    def test_phase_order_uses_the_five_manual_phase_keys(self):
        self.assertIn("function renderKickPhaseTimeIntegrity(record)", HTML)
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("['" + key + "'", HTML)

    def test_only_manual_confirmed_finite_timestamps_are_checked(self):
        self.assertIn("x.item?.confirmedBy==='parent_manual_review'", HTML)
        self.assertIn("x.item.status==='確認済み'&&Number.isFinite(x.item.timeSeconds)", HTML)

    def test_out_of_order_and_duplicate_timestamps_are_reported(self):
        self.assertIn("時刻が逆順", HTML)
        self.assertIn("同時刻", HTML)
        self.assertIn("時刻の再確認が必要", HTML)

    def test_missing_phases_do_not_produce_a_false_valid_result(self):
        self.assertIn("未確認の節目があり順序判定は途中", HTML)
        self.assertIn("未確認・時刻未登録", HTML)

    def test_no_automatic_timestamp_correction_or_inference(self):
        self.assertIn("時刻の自動修正・推測・並べ替えは行いません", HTML)

    def test_integrity_check_is_shown_for_each_angle_record(self):
        self.assertIn("renderKickPhaseTimeIntegrity(r)", HTML)
        self.assertIn("手動登録した節目", HTML)


if __name__ == "__main__":
    unittest.main()
