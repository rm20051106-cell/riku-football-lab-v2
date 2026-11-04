import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage39PhaseIntervalTimelineTests(unittest.TestCase):
    def test_intervals_follow_the_five_manual_phase_keys(self):
        self.assertIn("function renderKickPhaseIntervals(record)", HTML)
        for key in ("approach", "plant", "swing", "impact", "follow_through"):
            self.assertIn("['" + key + "'", HTML)

    def test_interval_requires_two_manual_confirmed_finite_times(self):
        self.assertIn("p?.confirmedBy==='parent_manual_review'&&p.status==='確認済み'&&Number.isFinite(p.timeSeconds)", HTML)

    def test_missing_or_reversed_times_are_not_calculated(self):
        self.assertIn("比較不可", HTML)
        self.assertIn("時刻順の再確認が必要", HTML)
        self.assertIn("b.time>=a.time", HTML)

    def test_interval_is_reference_not_skill_judgement(self):
        self.assertIn("動作の速さの良否や理想値は判定しません", HTML)

    def test_interval_timeline_is_integrated_per_video_record(self):
        self.assertIn("renderKickPhaseIntervals(r)", HTML)
        self.assertIn("renderKickPhaseTimeIntegrity(r)", HTML)


if __name__ == "__main__":
    unittest.main()
