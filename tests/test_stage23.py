import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

class Stage23RegressionTests(unittest.TestCase):
    def test_manual_confirmation_required(self):
        for token in ["function getStage23ConfirmedImprovements()", "isManuallyReviewedMatchEvent(ev)", "r.confirmed===true", "parent_manual_review", "未確認のAIコメント"]:
            self.assertIn(token, HTML)

    def test_dossier_and_weekly_plan_linkage(self):
        for token in ['id="stage23EvidenceLinkage"', "renderStage23EvidenceLinkage();", "stage23ConfirmedIssue:true", "手動確認済みの改善課題"]:
            self.assertIn(token, HTML)

    def test_video_storage_playback_and_backup_paths_preserved(self):
        for token in ["storeClipVideo(", "getClipVideo(", "playSavedClip(", "playSavedForm(", "function exportBackup", "function importBackup"]:
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
