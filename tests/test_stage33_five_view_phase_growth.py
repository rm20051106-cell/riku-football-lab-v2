import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


class Stage33FiveViewPhaseGrowthTests(unittest.TestCase):
    def test_form_capture_has_exact_five_standard_camera_views(self):
        block = HTML[HTML.index('id="formCameraAngle"'):HTML.index('</select>', HTML.index('id="formCameraAngle"'))]
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn("<option>" + angle + "</option>", block)
        self.assertEqual(block.count("<option>"), 6)  # five views plus 未選択

    def test_backend_guidance_supports_all_five_views_and_keeps_legacy_labels(self):
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn('"' + angle + '": [', BACKEND)
        self.assertIn('"横から": [', BACKEND)
        self.assertIn('"斜め後ろから": [', BACKEND)

    def test_auto_measurement_definitions_are_angle_specific(self):
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn("'" + angle + "':", HTML)
        self.assertIn("const rearMetrics=sideMetrics.filter", HTML)
        self.assertIn("const definitions=", HTML)

    def test_multi_angle_record_groups_same_foot_and_lists_five_views(self):
        self.assertIn("(x.foot||'右足')===(latest.foot||'右足')", HTML)
        for angle in ("右側から", "左側から", "斜め右後ろから", "斜め左後ろから", "後ろから"):
            self.assertIn("'" + angle + "'", HTML)

    def test_phase_timeline_keeps_bounded_samples_and_sampling_interval(self):
        self.assertIn("const phaseTimeline=rawFrames.slice(0,120)", HTML)
        self.assertIn("samplingIntervalSeconds:sm.sampling_interval_seconds??null", HTML)
        self.assertIn("timeline,phaseTimeline", HTML)

    def test_phase_comparison_requires_manual_confirmed_timestamps_on_both_records(self):
        self.assertIn("a?.confirmedBy==='parent_manual_review'&&a.status==='確認済み'&&Number.isFinite(a.timeSeconds)", HTML)
        self.assertIn("b?.confirmedBy==='parent_manual_review'&&b.status==='確認済み'&&Number.isFinite(b.timeSeconds)", HTML)

    def test_phase_comparison_uses_nearest_sample_without_interpolation(self):
        self.assertIn("const nearest=(record,time)=>", HTML)
        self.assertIn("x.time!==null&&x.time!==undefined&&Number.isFinite(Number(x.time))", HTML)
        self.assertIn("Math.abs(Number(best.time)-time)<=interval/2+0.051", HTML)
        self.assertIn("サンプル間の補間なし", HTML)
        self.assertIn("補間は行いません", HTML)

    def test_phase_comparison_requires_at_least_twenty_visible_landmarks(self):
        self.assertIn("Number(x.visible)>=20", HTML)
        self.assertIn("全身ランドマーク20個未満", HTML)

    def test_camera_setup_and_view_are_never_mixed(self):
        self.assertIn("const angleRecords=all.filter(x=>String(x.cameraAngle||'')===angle)", HTML)
        self.assertIn("getKickCameraSetup(x)", HTML)
        self.assertIn("撮影条件が違う記録は除外", HTML)

    def test_no_automatic_skill_improvement_judgement(self):
        self.assertIn("上達・良否の自動判定ではありません", HTML)
        self.assertIn("数値差はフォームの良否や上達を自動判定しません", HTML)


if __name__ == "__main__":
    unittest.main()
