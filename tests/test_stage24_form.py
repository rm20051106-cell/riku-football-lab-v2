import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

class Stage24FormPhaseTests(unittest.TestCase):
    def test_manual_phase_markers_are_explicit(self):
        for token in ["function markAiFormPhase()", "confirmedBy:'manual'", "助走開始", "軸足接地", "蹴り足振り始め", "インパクト", "フォロースルー終了"]:
            self.assertIn(token, HTML)

    def test_phase_marker_requires_same_source_video(self):
        self.assertIn("getVideoSourceKey(file)!==latest.sourceVideoKey", HTML)
        self.assertIn("別動画への誤登録を防ぐ", HTML)

    def test_comparison_uses_same_manual_phase_and_nearest_sample(self):
        for token in ["function getAiFormPhaseValue(record,marker)", "newer.phaseMarkers", "older.phaseMarkers", "手動確認した同じ動作の節目で比較", "節目そのものの瞬間値とは限りません"]:
            self.assertIn(token, HTML)

    def test_missing_metrics_are_not_zero(self):
        self.assertIn("a!==null&&a!==undefined&&b!==null&&b!==undefined", HTML)

    def test_video_storage_playback_and_backup_paths_preserved(self):
        for token in ["storeClipVideo(", "getClipVideo(", "playSavedClip(", "playSavedForm(", "async function exportData()", "importFile.addEventListener"]:
            self.assertIn(token, HTML)

    def test_inline_javascript_syntax(self):
        scripts = re.findall(r"<script(?:\\s[^>]*)?>([\\s\\S]*?)</script>", HTML, re.I)
        self.assertTrue(scripts, "inline script not found")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as f:
            f.write("\\n".join(scripts))
            f.flush()
            result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == "__main__":
    unittest.main()
