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

    def test_manual_match_assessment_provenance_survives_initial_scan_save(self):
        self.assertIn("if(field==='assessment'){event.assessment_source='manual';", HTML)
        self.assertIn("assessmentSource:ev.assessment_source==='manual'?'manual':null", HTML)
        self.assertIn("manualAssessmentAt:ev.manual_assessment_at||null", HTML)

    def test_training_reflection_resolves_only_current_manually_confirmed_match_evidence(self):
        self.assertIn("function getValidatedTrainingMatchEvents(record)", HTML)
        self.assertIn("isManuallyReviewedMatchEvent(event)", HTML)
        self.assertIn("event.assessmentSource!=='manual'", HTML)
        self.assertIn("const linked=getValidatedTrainingMatchEvents(record);", HTML)

    def test_training_checklist_progress_deduplicates_and_rejects_invalid_indexes(self):
        self.assertIn("function getCompletedTrainingStepIndexes(record,stepsOverride)", HTML)
        self.assertIn("new Set(done.filter(index=>Number.isInteger(index)", HTML)
        self.assertIn("getCompletedTrainingStepIndexes(t,steps).length/steps.length*100", HTML)

    def test_weekly_plan_uses_explicitly_manual_match_evidence(self):
        self.assertIn("ev.decisionReviewSource='manual'", HTML)
        self.assertIn("const assessmentEvents=events.filter(e=>e.assessmentSource==='manual'", HTML)
        self.assertIn("const decisionEvents=events.filter(e=>e.decisionReviewSource==='manual')", HTML)

    def test_selected_match_growth_goal_flows_into_next_week_plan(self):
        self.assertIn("growthGoalCandidate=state.settings?.nextMatchGoal?.source==='manual-reviewed-match-growth'", HTML)
        self.assertIn("growthGoalAgeDays>=0&&growthGoalAgeDays<7?growthGoalCandidate:null", HTML)
        self.assertIn("||growthGoal?.focus||", HTML)
        self.assertIn("goalText=growthGoal?.note||goal?.goal", HTML)

    def test_next_match_growth_goal_expires_after_seven_days(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 15)
        plan = HTML[start:end]
        self.assertIn("growthGoalAgeDays>=0&&growthGoalAgeDays<7?growthGoalCandidate:null", plan)
        self.assertIn("growthGoalCandidate?.date", plan)
        self.assertIn("growthGoalAgeDays!==null", plan)

    def test_explicit_match_growth_goal_has_final_priority_in_weekly_plan(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 15)
        plan = HTML[start:end]
        self.assertIn("if(growthGoal){primary.title='試合成長目標｜'", plan)
        self.assertIn("primary.focus=growthGoal.focus", plan)
        self.assertIn("primary.category='試合成長目標'", plan)
        self.assertIn("primary.sourceMatch={...(primary.sourceMatch||{}),matchGrowthGoal:true", plan)
        self.assertLess(plan.index("if(feedback.assessed)"), plan.index("if(growthGoal){primary.title="))

    def test_training_step_save_failure_rolls_back_progress(self):
        start = HTML.index("function updateTrainingStep(")
        end = HTML.index("\nfunction ", start + 15)
        handler = HTML[start:end]
        self.assertIn("const original=JSON.parse(JSON.stringify(record));", handler)
        self.assertIn("if(!persist())", handler)
        self.assertIn("Object.keys(record).forEach(key=>delete record[key]);Object.assign(record,original);", handler)
        self.assertIn("変更前の記録に戻しました", handler)

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
        self.assertIn("backupFormat:'riku-football-lab',backupVersion:3", HTML)
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

    def test_positioning_review_uses_safe_persist_and_rolls_back(self):
        start = HTML.index("function updateMatchPositioning(")
        end = HTML.index("\nfunction ", start + 15)
        update = HTML[start:end]
        self.assertIn("const originalReview=ev.positioningReview?{...ev.positioningReview}:null", update)
        self.assertIn("if(!persist()){", update)
        self.assertIn("else delete ev.positioningReview", update)
        self.assertIn("renderAll();", update)
        self.assertNotIn("localStorage.setItem(KEY", update)

    def test_next_match_growth_goal_is_restored_when_persist_fails(self):
        start = HTML.index("function applyMatchGrowthGoal(")
        end = HTML.index("\nfunction ", start + 15)
        update = HTML[start:end]
        self.assertIn("const previousGoal=state.settings.nextMatchGoal?", update)
        self.assertIn("if(!persist()){", update)
        self.assertIn("else delete state.settings.nextMatchGoal", update)
        self.assertIn("元の目標を維持しています", update)



    def test_video_storage_progress_and_retry_controls_are_present(self):
        for token in ("videoSaveProgressBar", "formSaveProgressBar", "videoImportProgressBar", "videoImportRetry", "retryFailedVideoImport", "updateVideoTaskProgress"):
            self.assertIn(token, HTML)
        self.assertIn("lastVideoImportFiles=files", HTML)
        self.assertIn("保存前の容量を確認しています", HTML)

    def test_storage_usage_is_visualized_and_restore_errors_keep_retry(self):
        self.assertIn("videoStorageUsageBar", HTML)
        self.assertIn('aria-label="ブラウザ保存領域の使用率"', HTML)
        self.assertIn("lastVideoImportFiles=files", HTML)
        self.assertIn("retryFailedVideoImport", HTML)
        self.assertIn("再試行できます", HTML)


    def test_match_growth_graph_uses_only_manual_evidence_and_minimum_sample(self):
        self.assertIn("function renderGrowthTrendChart(rows)", HTML)
        self.assertIn("row.total>=2&&Number.isFinite(row.rate)", HTML)
        self.assertIn("renderGrowthTrendChart(item.rows)", HTML)
        self.assertIn("手動評価の推移", HTML)

    def test_position_decision_history_is_broken_down_by_match(self):
        self.assertIn("byMatch:[]", HTML)
        self.assertIn("matchRow.qualityCount++", HTML)
        self.assertIn("matchRow.scanCount++", HTML)
        self.assertIn("試合ごとの時系列（直近6試合）", HTML)

    def test_ai_form_analysis_links_to_same_match_video_and_rolls_back(self):
        self.assertIn("function connectAiFormAnalysisToMatch(analysis,match)", HTML)
        self.assertIn("syncAiFormAnalysisMatchLinks(analysis)", HTML)
        self.assertIn("previousAiFormAnalyses=JSON.parse(JSON.stringify(state.aiFormAnalyses||[]))", HTML)
        self.assertIn("state.aiFormAnalyses=previousAiFormAnalyses", HTML)
        self.assertIn("playSavedClip('+Number(linkedMatch.clipId)+')", HTML)

    def test_backup_v3_manifest_is_verified_and_ai_links_rebuilt_on_restore(self):
        self.assertIn("backupVersion:3,recordCounts:", HTML)
        self.assertIn("バックアップ目録と一致しません", HTML)
        self.assertIn("if(isAppBackup&&parsed.backupVersion>3)", HTML)
        self.assertIn("restored.aiFormAnalyses||[]).forEach(analysis=>", HTML)
        self.assertIn("analysis.matchId=String(match.id)", HTML)

    def test_weekly_adjustment_includes_position_decision_training_candidate(self):
        self.assertIn("const positionPlan=getPositionDecisionTrainingPlan()", HTML)
        self.assertIn("ポジション別の判断・周囲確認評価からの練習候補", HTML)


if __name__ == "__main__":
    unittest.main()
