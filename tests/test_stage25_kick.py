import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

class Stage25KickFormTests(unittest.TestCase):
    def test_six_kick_form_dimensions_are_separate(self):
        for token in ["plantBallDistance", "plantFootDirection", "swingPath", "impactPosition", "trunkLean", "followThrough"]:
            self.assertIn(token, HTML)
        self.assertIn("右足キック専用", HTML)
        self.assertIn("この評価表は右足キック専用です", HTML)

    def test_ai_measurements_and_parent_review_are_separated(self):
        self.assertIn("AI参考値＋手動確認", HTML)
        self.assertIn("一部AI計測＋手動確認", HTML)
        self.assertIn("parent_manual_review", HTML)
        self.assertIn("改善が必要", HTML)
        self.assertIn("未確認", HTML)

    def test_camera_distance_and_framing_are_saved_and_compared(self):
        for token in ["formCameraDistance", "formFraming", "cameraDistance:extra.camera_distance", "framing:extra.framing", "getKickCameraSetup(record)", "5条件が同じ記録のみ"]:
            self.assertIn(token, HTML)

    def test_quality_check_does_not_claim_certainty(self):
        for token in ["撮影信頼性チェック", "姿勢サンプル", "映像品質やフォーム精度を保証するものではありません", "全身とボール"]:
            self.assertIn(token, HTML)

    def test_video_storage_playback_backup_paths_preserved(self):
        for token in ["storeClipVideo(", "getClipVideo(", "playSavedClip(", "playSavedForm(", "async function exportData()", "importFile.addEventListener"]:
            self.assertIn(token, HTML)

    def test_inline_javascript_syntax(self):
        scripts = re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", HTML, re.I)
        self.assertTrue(scripts, "inline script not found")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as f:
            f.write("\n".join(scripts))
            f.flush()
            result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == "__main__":
    unittest.main()
