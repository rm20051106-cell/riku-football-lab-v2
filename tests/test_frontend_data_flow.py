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

    def test_explicit_match_growth_goal_has_final_priority_in_weekly_plan(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 15)
        plan = HTML[start:end]
        self.assertIn("if(growthGoal){primary.title='試合成長目標｜'", plan)
        self.assertIn("primary.focus=growthGoal.focus", plan)
        self.assertIn("primary.category='試合成長目標'", plan)
        self.assertIn("primary.sourceMatch={...(primary.sourceMatch||{}),matchGrowthGoal:true", plan)
        self.assertLess(plan.index("if(feedback.assessed)"), plan.index("if(growthGoal){primary.title="))

    def test_training_save_failure_preserves_form_and_source_link(self):
        self.assertIn("if(!persist()){\n  state.trainings=state.trainings.filter", HTML)
        self.assertIn("pendingTrainingSource=source;renderAll();", HTML)

    def test_match_evidence_keeps_match_identity_for_duplicate_event_ids(self):
        self.assertIn("map(e=>({...e,matchId:m.id,matchDate:m.date,matchTitle:m.title}))", HTML)
        self.assertIn("String(e.matchId)+'|'+String(e.id)", HTML)

    def test_match_review_validation_precedes_mutation_and_save_rolls_back(self):
        validation = HTML.index("if(actualChoice&&availableOptions.length&&!availableOptions.includes(actualChoice))")
        mutation = HTML.index("markManualMatchReview(ev,review)", validation)
        self.assertLess(validation, mutation)
        self.assertIn("const originalEvent=JSON.parse(JSON.stringify(ev)),originalTrainings=JSON.parse(JSON.stringify(state.trainings||[]))", HTML)
        self.assertIn("if(!persist()){\n  Object.keys(ev).forEach(key=>delete ev[key]);Object.assign(ev,originalEvent);state.trainings=originalTrainings", HTML)

    def test_backup_integrity_and_separate_video_export_restore(self):
        self.assertIn("backupFormat:'riku-football-lab',backupVersion:2", HTML)
        self.assertIn("videoFilesIncluded:false", HTML)
        self.assertIn("stateSha256", HTML)
        self.assertIn("async function prepareVideoExport()", HTML)
        self.assertIn("riku-video__'+encodeURIComponent(x.key)+'__'+encodeURIComponent(name)", HTML)
        self.assertIn("if(actual.toLowerCase()!==String(parsed.stateSha256).toLowerCase())", HTML)
        self.assertIn("const markedVideos=[...(imported.clips||[]),...(imported.forms||[])].filter(x=>x.hasVideo).length", HTML)

    def test_restore_rejects_invalid_names_and_checks_storage_bytes(self):
        self.assertIn("if(!key||key.startsWith('__pending_')||!name)", HTML)
        self.assertIn("await compareVideoBlobs(existing.blob,restoredFile)", HTML)
        self.assertIn("await compareVideoBlobs(verified.blob,restoredFile)", HTML)
        self.assertIn("const incomingBytes=files.reduce((n,f)=>n+Number(f.size||0),0)", HTML)
        self.assertIn("await scanSavedVideoIntegrity()", HTML)

    def test_both_video_players_expose_error_load_play_and_end_states(self):
        for event in ("onerror", "onloadeddata", "onplay", "onended"):
            self.assertIn("matchVideo." + event, HTML)
            self.assertIn("formVideo." + event, HTML)
        self.assertIn("URL.createObjectURL(saved.blob)", HTML)
        self.assertIn("URL.revokeObjectURL(matchVideo.dataset.objectUrl)", HTML)
        self.assertIn("URL.revokeObjectURL(formVideo.dataset.objectUrl)", HTML)

    def test_video_integrity_scan_detects_orphans_missing_and_duplicate_keys(self):
        for token in ("const missing=records.filter", "const unlinked=records.filter", "const orphan=data.keys.map", "const duplicateRecordKeys=records.map", "const duplicateGroups=[]"):
            self.assertIn(token, HTML)

    def test_corrupt_backup_does_not_replace_current_local_data(self):
        self.assertIn("const previousState=state,previousStoredState=localStorage.getItem(KEY)", HTML)
        self.assertIn("throw Error('バックアップの内容が書き出し後に変更・破損した可能性があります。現在の記録を保護するため復元を中止しました')", HTML)
        self.assertIn("state=previousState;try{if(previousStoredState!==null)localStorage.setItem(KEY,previousStoredState)", HTML)


if __name__ == "__main__":
    unittest.main()
