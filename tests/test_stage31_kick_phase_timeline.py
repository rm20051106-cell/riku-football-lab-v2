import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


class Stage31KickPhaseTests(unittest.TestCase):
    def test_form_sampling_is_two_fps_with_bounded_frame_count(self):
        self.assertIn('target_sample_rate = MATCH_SAMPLE_RATE if mode == "match" else 2.0', BACKEND)
        self.assertIn('max_samples = MATCH_MAX_SAMPLES if mode == "match" else 120', BACKEND)

    def test_candidates_are_based_on_visible_foot_motion_and_time(self):
        self.assertIn("def build_kick_phase_candidates(frames, sampling_interval_seconds, preferred_foot="right"):", BACKEND)
        self.assertIn('frame.get(side + "_foot_image_motion_per_sec")', BACKEND)
        self.assertIn('interval <= 0.75 and len(valid) >= 4', BACKEND)
        self.assertIn('"peak_candidate"', BACKEND)
        self.assertIn('"post_peak_candidate"', BACKEND)

    def test_unobservable_phases_are_never_fabricated(self):
        self.assertIn('"approach", "label": "助走", "status": "manual_review_required"', BACKEND)
        self.assertIn('"plant", "label": "軸足接地", "status": "manual_review_required"', BACKEND)
        self.assertIn('"impact", "label": "インパクト", "status": "manual_review_required"', BACKEND)
        self.assertIn("接触位置・時刻", BACKEND)

    def test_frontend_displays_and_persists_phase_timeline(self):
        self.assertIn("function renderKickPhaseCandidates(data,dominantFoot)", HTML)
        self.assertIn("renderKickPhaseCandidates(summary.kick_phase_candidates,extra.dominant_foot)", HTML)
        self.assertIn("kickPhaseCandidates:sm.kick_phase_candidates||null", HTML)
        self.assertIn("自動候補は画像上の足先移動から抽出した目安", HTML)


if __name__ == "__main__":
    unittest.main()
