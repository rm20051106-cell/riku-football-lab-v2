import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

class Stage26KickPhaseTests(unittest.TestCase):
    def test_manual_markers_are_the_only_phase_authority(self):
        self.assertIn("confirmedBy:'manual'", HTML)
        self.assertIn("助走開始','軸足接地','蹴り足振り始め','インパクト','フォロースルー終了", HTML)
        self.assertIn("節目は保護者が手動登録", HTML)
        self.assertIn("自動特定", HTML)

    def test_each_phase_shows_separate_pose_metrics(self):
        for token in ["rightKnee", "leftKnee", "rightHip", "leftHip", "trunk", "rightFootMotion", "leftFootMotion"]:
            self.assertIn(token, HTML)
        self.assertIn("offsetSeconds", HTML)
        self.assertIn("検出ランドマーク20個未満", HTML)

    def test_phase_durations_require_both_manual_markers(self):
        self.assertIn("item.n&&prev.n?item.n.timeSeconds-prev.n.timeSeconds:null", HTML)
        self.assertIn("item.o&&prev.o?item.o.timeSeconds-prev.o.timeSeconds:null", HTML)
        self.assertIn("節目が両方そろっている区間のみ表示", HTML)

    def test_unmeasured_foot_and_ball_contact_not_inferred(self):
        self.assertIn("足先の正確な位置や接触を示しません", HTML)
        self.assertIn("インパクト位置", HTML)
        self.assertIn("未確認", HTML)

    def test_comparison_requires_all_five_capture_conditions(self):
        self.assertIn("getKickCameraSetup(record)", HTML)
        self.assertIn("cameraAngle||'未設定',record.cameraDistance||'未設定',record.framing||'未設定',record.kind||'シュート',record.foot||'右足'", HTML)

    def test_parent_confirmed_issue_flows_to_training(self):
        self.assertIn("parent_manual_kick_review", HTML)
        self.assertIn("renderAiFormPracticePlan()", HTML)
        self.assertIn("シュートフォーム", HTML)

    def test_video_save_playback_backup_handlers_remain(self):
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
