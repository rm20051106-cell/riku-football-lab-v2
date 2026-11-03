import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

class Stage27MultiAngleTests(unittest.TestCase):
    def test_same_kick_id_is_saved_with_each_analysis(self):
        self.assertIn('id="formKickGroupId"', HTML)
        self.assertIn("kick_group_id:", HTML)
        self.assertIn("kickGroupId:String(extra.kick_group_id||'').trim().slice(0,40)", HTML)
        self.assertIn("x.kickGroupId===latest.kickGroupId", HTML)

    def test_angle_visibility_is_manual_and_persisted(self):
        for field in ["plantFoot", "kickingLeg", "trunk", "footAndBall"]:
            self.assertIn(field, HTML)
            self.assertIn("kick-visible-", HTML)
        for status in ["明瞭", "一部のみ", "隠れている", "未確認"]:
            self.assertIn(status, HTML)
        self.assertIn("latest.angleVisibility=", HTML)

    def test_only_parent_marked_phase_timestamps_are_listed(self):
        self.assertIn("m.confirmedBy==='manual'", HTML)
        for phase in ["助走開始", "軸足接地", "蹴り足振り始め", "インパクト", "フォロースルー終了"]:
            self.assertIn(phase, HTML)
        self.assertIn("手動登録した節目", HTML)

    def test_different_angles_are_not_numerically_compared(self):
        self.assertIn("異なる撮影角度の関節角度・移動量を直接比較したり、改善判定したりしません", HTML)
        self.assertIn("cameraAngle||'未設定'", HTML)

    def test_manual_issue_still_links_to_training_plan(self):
        self.assertIn("parent_manual_kick_review", HTML)
        self.assertIn("renderAiFormPracticePlan()", HTML)
        self.assertIn("シュートフォーム", HTML)

    def test_video_save_playback_and_backup_handlers_remain(self):
        for token in ["storeClipVideo(", "getClipVideo(", "playSavedClip(", "playSavedForm(", "async function exportData()", "importFile.addEventListener", "prepareVideoExport()", "importVideoFiles(event)"]:
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
