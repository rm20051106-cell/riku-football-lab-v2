from pathlib import Path
import unittest

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class FrontendDataFlowContracts(unittest.TestCase):
    def test_video_blob_validation_and_unique_record_ids(self):
        self.assertIn("function validateStoredVideoBlob(blob)", HTML)
        self.assertIn("async function storeClipVideo(id,file){validateStoredVideoBlob(file);", HTML)
        self.assertIn("function nextUniqueRecordId(...collections)", HTML)

    def test_video_restore_verifies_bytes_and_rolls_back_failed_metadata(self):
        self.assertIn("await compareVideoBlobs(verified.blob,restoredFile)", HTML)
        self.assertIn("const saved=persist();if(!saved){for(const [key,original] of originalFlags)", HTML)
        self.assertIn("await restoreClipVideoRecord(key,previous)", HTML)

    def test_saved_video_playback_reports_load_play_and_completion(self):
        for event in ("onloadeddata", "onplay", "onended"):
            self.assertIn("matchVideo." + event, HTML)
            self.assertIn("formVideo." + event, HTML)
        self.assertIn("URL.createObjectURL(saved.blob)", HTML)
        self.assertIn("URL.revokeObjectURL(matchVideo.dataset.objectUrl)", HTML)

    def test_video_metadata_and_user_notes_are_saved_atomically(self):
        self.assertIn("if(!persist()){state.clips=state.clips.filter", HTML)
        self.assertIn("if(!persist()){state.forms=state.forms.filter", HTML)
        self.assertIn("clipGood.value='';clipImprove.value='';if(record.hasVideo)", HTML)
        self.assertIn("formNote.value='';if(record.hasVideo)", HTML)

    def test_growth_timeline_uses_manual_evidence_and_all_match_dates(self):
        for category in ("加速ドリブル", "切り返し", "判断力", "ポジショニング"):
            self.assertIn("key:'" + category + "'", HTML)
        self.assertIn("ev.manualGrowthSource==='manual'", HTML)
        self.assertIn("ev.assessmentSource==='manual'", HTML)
        self.assertIn("const allMatchDates=[...new Set(matches.map(m=>String(m.date||'')).filter(Boolean))].sort();", HTML)

    def test_weekly_plan_uses_explicitly_manual_match_evidence(self):
        self.assertIn("ev.decisionReviewSource='manual'", HTML)
        self.assertIn("const assessmentEvents=events.filter(e=>e.assessmentSource==='manual'", HTML)
        self.assertIn("const decisionEvents=events.filter(e=>e.decisionReviewSource==='manual')", HTML)

    def test_selected_match_growth_goal_flows_into_next_week_plan(self):
        self.assertIn("growthGoal=state.settings?.nextMatchGoal?.source==='manual-reviewed-match-growth'", HTML)
        self.assertIn("||growthGoal?.focus||", HTML)
        self.assertIn("goalText=growthGoal?.note||goal?.goal", HTML)

    def test_training_save_failure_preserves_form_and_source_link(self):
        self.assertIn("if(!persist()){\n  state.trainings=state.trainings.filter", HTML)
        self.assertIn("pendingTrainingSource=source;renderAll();", HTML)


if __name__ == "__main__":
    unittest.main()
