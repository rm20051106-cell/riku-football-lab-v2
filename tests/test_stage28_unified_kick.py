import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage28UnifiedKickTests(unittest.TestCase):
    def test_same_kick_is_rendered_as_one_unified_record(self):
        self.assertIn("function renderMultiAngleKickReview()", HTML)
        self.assertIn("String(x.kickGroupId||'')===groupId", HTML)
        self.assertIn("統合フォーム記録", HTML)
        self.assertIn("角度別の証拠と動画", HTML)

    def test_each_angle_keeps_its_own_evidence_and_manual_review(self):
        for token in ["cameraAngle", "angleVisibility", "kickFormReview", "phaseMarkers", "parent_manual_review"]:
            self.assertIn(token, HTML)
        self.assertIn("同じ項目を複数角度で確認できた場合", HTML)
        self.assertIn("角度・日付・手動確認内容", HTML)

    def test_unconfirmed_values_are_never_filled_or_counted(self):
        self.assertIn("if(review.confirmedBy!=='parent_manual_review')return []", HTML)
        self.assertIn("未確認を課題として補完しません", HTML)
        self.assertIn("本人確認済みの改善課題はありません", HTML)

    def test_no_cross_angle_metric_averaging_or_comparison(self):
        self.assertIn("異なる角度の数値を平均・合算せず", HTML)
        self.assertIn("同じ角度でも撮影距離・画角・キック条件が一致しない場合は比較しません", HTML)
        self.assertIn("value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))", HTML)

    def test_confirmed_improvement_issues_feed_practice_plan(self):
        self.assertIn("manualKickIssues", HTML)
        self.assertIn("manualKickPlanHtml", HTML)
        self.assertIn("同一キックの手動確認から翌週へ引き継ぐ課題", HTML)
        self.assertIn("練習後は、同じ項目を手動で再確認", HTML)

    def test_video_playback_and_backup_regressions_remain(self):
        for token in ["playSavedForm(", "storeClipVideo(", "getClipVideo(", "async function exportData()", "importFile.addEventListener", "prepareVideoExport()", "importVideoFiles(event)"]:
            self.assertIn(token, HTML)

    def test_stage27_manual_marker_and_angle_flow_remains(self):
        for token in ["confirmedBy:'manual'", "function markAiFormPhase()", "function saveKickManualReview()", "kickGroupId:String(extra.kick_group_id||'').trim().slice(0,40)"]:
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
