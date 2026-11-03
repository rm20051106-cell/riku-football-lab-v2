import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage29KickFormGrowthTests(unittest.TestCase):
    def test_growth_comparison_has_dedicated_ui_and_renderer(self):
        self.assertIn('id="kickFormGrowthCompare"', HTML)
        self.assertIn("function renderKickFormGrowthComparison()", HTML)
        self.assertIn("renderKickFormGrowthComparison();", HTML)

    def test_comparisons_are_separated_by_angle_and_exact_setup(self):
        self.assertIn("const angleNames=['横','正面','斜め後ろ']", HTML)
        self.assertIn("getKickCameraSetup(x)===setup", HTML)
        self.assertIn("撮影条件が違う記録は除外", HTML)
        self.assertIn("同じ角度・撮影距離・画角・キック種別・利き足", HTML)

    def test_manual_growth_requires_both_parent_confirmations(self):
        self.assertIn("manualA.confirmedBy==='parent_manual_review'&&manualB.confirmedBy==='parent_manual_review'", HTML)
        self.assertIn("a.status==='未確認'||b.status==='未確認'", HTML)
        self.assertIn("手動確認済みの項目がそろっていない", HTML)

    def test_ai_metrics_are_reference_only_not_automatic_improvement(self):
        self.assertIn("数値差はフォームの良否や上達を自動判定しません", HTML)
        self.assertIn("（参考値）", HTML)
        self.assertIn("Number.isFinite(a)&&Number.isFinite(b)", HTML)

    def test_visibility_quality_and_unknowns_remain_explicit(self):
        self.assertIn("Number(x.visible)>=20", HTML)
        self.assertIn("欠測は比較対象外", HTML)
        self.assertIn("未確認", HTML)

    def test_video_playback_backup_and_multi_angle_regressions_remain(self):
        for token in ["playSavedForm(", "storeClipVideo(", "getClipVideo(", "async function exportData()", "importFile.addEventListener", "prepareVideoExport()", "importVideoFiles(event)", "function renderMultiAngleKickReview()"]:
            self.assertIn(token, HTML)

    def test_inline_javascript_syntax(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", HTML, re.I | re.S)
        self.assertTrue(scripts, "inline script not found")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as f:
            f.write("\n".join(scripts))
            f.flush()
            result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
