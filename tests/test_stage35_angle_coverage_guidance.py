import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage35AngleCoverageGuidanceTests(unittest.TestCase):
    def test_coverage_guidance_uses_five_official_views(self):
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn("'" + angle + "'", HTML)
        self.assertIn("function renderFiveViewCoverageGuidance(records,officialAngles)", HTML)

    def test_guidance_distinguishes_confirmed_unobservable_pending_and_unshot(self):
        for label in ("確認済み", "この角度では確認できず", "未確認", "未撮影"):
            self.assertIn("'" + label + "'", HTML)

    def test_only_manual_confirmation_is_counted_as_confirmed(self):
        self.assertIn("p.confirmedBy!=='parent_manual_review'", HTML)
        self.assertIn("p.status==='確認済み'&&Number.isFinite(p.timeSeconds)", HTML)

    def test_latest_record_per_angle_is_used(self):
        self.assertIn("latestByAngle.set(angle,matches[matches.length-1])", HTML)

    def test_existing_pending_video_is_reviewed_before_retake(self):
        self.assertIn("まず撮影済みの「'+pending.join('・')+'」の動画を再生し、手動確認してください。", HTML)

    def test_missing_angle_requests_capture_with_same_kick_identity(self):
        self.assertIn("追加撮影が必要な視点", HTML)
        self.assertIn("同じキックID・キック種別・利き足", HTML)

    def test_unobservable_is_not_filled_from_other_angles(self):
        self.assertIn("他視点の確認結果で補完したりしません", HTML)
        self.assertIn("全撮影済み視点で未確認です。別視点で撮り直す", HTML)

    def test_guidance_is_integrated_before_evidence_matrix(self):
        self.assertIn("renderFiveViewCoverageGuidance(records,officialAngles)+renderFiveViewPhaseEvidenceMatrix(records,officialAngles)", HTML)


if __name__ == "__main__":
    unittest.main()
