from pathlib import Path
import unittest

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class FrontendDataFlowContracts(unittest.TestCase):
    def test_video_blob_validation_and_unique_record_ids(self):
        self.assertIn("function validateStoredVideoBlob(blob)", HTML)
        self.assertIn("async function storeClipVideo(id,file){\n validateStoredVideoBlob(file);", HTML)
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
        self.assertIn("previousMatchAnalyses=JSON.parse(JSON.stringify(state.matchAnalyses||[]))", HTML)
        self.assertIn("state.aiFormAnalyses=previousAiFormAnalyses;state.matchAnalyses=previousMatchAnalyses", HTML)
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


    def test_stage17_growth_forecast_requires_three_manual_match_samples(self):
        start = HTML.index("function getGrowthForecastData()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("row.total>=2&&Number.isFinite(row.rate)", fn)
        self.assertIn("points.length<4", fn)
        self.assertIn("Math.max(0,Math.min(100", fn)
        self.assertIn("直近試合を重視した中央値と傾向", HTML)
        self.assertIn("intervalLow", fn)
        self.assertIn("intervalHigh", fn)
        self.assertIn("mad", fn)
        self.assertIn("sceneCount", fn)

    def test_stage17_training_match_comparison_uses_manual_same_focus_events(self):
        start = HTML.index("function getManualMatchOutcomeEvents(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("isManuallyReviewedMatchEvent(ev)", fn)
        self.assertIn("ev.assessmentSource==='manual'", fn)
        self.assertIn("getTrainingFocusForMatchEvent(ev)===focus", fn)
        self.assertIn("beforeRate", HTML)
        self.assertIn("afterRate", HTML)
        self.assertIn("練習の因果効果を示すものではなく", HTML)

    def test_stage17_situation_breakdown_requires_explicit_role_and_action(self):
        start = HTML.index("function getSituationDecisionBreakdown()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("isManuallyReviewedMatchEvent(ev)", fn)
        self.assertIn("!ev.positionRole||!ev.actionType", fn)
        self.assertIn("ev.positioningReview", fn)
        self.assertIn("x.scenes>=2", fn)

    def test_stage17_ai_form_history_compares_only_matching_capture_setup(self):
        start = HTML.index("function renderAiFormCompare()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("sameSetup(x)", fn)
        self.assertIn("slice(0,5)", fn)
        self.assertIn("同条件の過去記録", fn)
        self.assertIn("角度差は改善判定ではありません", fn)

    def test_stage17_weekly_plan_uses_training_match_pairs_without_causal_claim(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("getTrainingMatchCorrelationData()", fn)
        self.assertIn("filter(x=>x.count>=2)", fn)
        self.assertIn("練習の因果効果を示すものではなく", fn)

    def test_stage17_backup_restore_preserves_all_growth_evidence_and_rolls_back(self):
        export_start = HTML.index("async function exportData()")
        import_start = HTML.index("importFile.addEventListener", export_start)
        import_end = HTML.index("function clearData()", import_start)
        backup_export = HTML[export_start:import_start]
        backup_import = HTML[import_start:import_end]
        self.assertIn("recordCounts:", backup_export)
        self.assertIn("stateSha256", backup_export)
        self.assertIn("videoFilesIncluded:false", backup_export)
        self.assertIn("state", backup_export)
        self.assertIn("const previousState=state,previousStoredState=localStorage.getItem(KEY)", backup_import)
        self.assertIn("state=previousState", backup_import)
        self.assertIn("previousStoredState!==null", backup_import)
        self.assertIn("analysis.matchId=String(match.id)", backup_import)
        self.assertIn("match.aiFormAnalysisIds.push(analysis.id)", backup_import)
        self.assertIn("localStorage.setItem(KEY,serialized);state=restored;renderAll()", backup_import)


    def test_stage18_forecast_uses_robust_median_and_displays_uncertainty(self):
        start = HTML.index("function getGrowthForecastData()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("points.length<4", fn)
        self.assertIn("const median=values=>", fn)
        self.assertIn("slopes.push", fn)
        self.assertIn("const margin=Math.min(45", fn)
        self.assertIn("confidence", fn)
        self.assertIn("sceneCount", fn)
        self.assertIn("%目安（'+row.intervalLow+'〜'+row.intervalHigh+'%）", HTML)
        self.assertIn("予測精度を保証しません", HTML)

    def test_stage18_training_match_comparison_requires_comparable_samples(self):
        start = HTML.index("function getTrainingMatchCorrelationData()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("dayDistance(match.date,training.date)<=30", fn)
        self.assertIn("expectedRole", fn)
        self.assertIn("matchEvents(match).length>=2", fn)
        self.assertIn("pre.length<2||post.length<2", fn)
        self.assertIn("beforeScenes:pre.length", fn)
        self.assertIn("afterScenes:post.length", fn)
        self.assertIn("前後各2件以上", HTML)

    def test_stage18_backup_restore_still_verifies_hash_before_mutation(self):
        import_start = HTML.index("importFile.addEventListener")
        import_end = HTML.index("function clearData()", import_start)
        restore = HTML[import_start:import_end]
        self.assertLess(restore.index("crypto.subtle.digest"), restore.index("const restored="))
        self.assertIn("actual.toLowerCase()!==String(parsed.stateSha256).toLowerCase()", restore)
        self.assertIn("state=previousState", restore)
        self.assertIn("既存の端末内動画は自動削除しません", restore)




    def test_stage19_priority_board_uses_only_comparable_manual_match_evidence(self):
        start = HTML.index("function getMatchGrowthPriorityBoard()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("latest.total<2", fn)
        self.assertIn("status==='再確認が必要'", fn)
        self.assertIn("latest.improve>latest.good", fn)
        self.assertIn("evidenceCount:latest.total", fn)
        self.assertIn("getMatchGrowthTimelineData()", fn)

    def test_stage19_long_term_growth_requires_two_matches_with_two_manual_scenes(self):
        start = HTML.index("function getLongTermGrowthSummary()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("row.total>=2&&Number.isFinite(row.rate)", fn)
        self.assertIn("if(valid.length<2)", fn)
        self.assertIn("trainingSessions", fn)
        self.assertIn("trainingMinutes", fn)
        self.assertIn("delta", fn)

    def test_stage19_weekly_plan_uses_prioritized_manual_growth_issue(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("getMatchGrowthPriorityBoard()", fn)
        self.assertIn("if(growthPriority&&!growthGoal)", fn)
        self.assertIn("growthPriority.evidenceCount", fn)
        self.assertIn("本人確認済みの複数場面から課題を優先", fn)

    def test_stage19_report_displays_long_term_comparison_and_priority(self):
        self.assertIn("function renderLongTermGrowthSummary()", HTML)
        self.assertIn("長期成長比較", HTML)
        self.assertIn("優先度 ", HTML)
        self.assertIn("getMatchGrowthPriorityBoard().filter", HTML)

    def test_stage19_backup_restore_and_saved_video_playback_contracts_remain(self):
        self.assertIn("actual.toLowerCase()!==String(parsed.stateSha256).toLowerCase()", HTML)
        self.assertIn("state=previousState", HTML)
        self.assertIn("await compareVideoBlobs(verified.blob,restoredFile)", HTML)
        self.assertIn("URL.createObjectURL(saved.blob)", HTML)
        self.assertIn("matchVideo.onloadeddata", HTML)
        self.assertIn("formVideo.onloadeddata", HTML)


    def test_stage20_player_dossier_uses_only_manual_confirmed_match_assessments(self):
        start = HTML.index("function getPlayerDossierSummary()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("isManuallyReviewedMatchEvent(event)", fn)
        self.assertIn("event.assessmentSource==='manual'", fn)
        self.assertIn("['良かった','改善したい'].includes(event.assessment)", fn)
        self.assertIn("row.matches.size>=2&&row.total>=2&&row.good>=2&&row.good>row.improve", fn)
        self.assertIn("row.matches.size>=2&&row.total>=2&&row.improve>=2&&row.improve>row.good", fn)

    def test_stage20_dossier_integrates_matches_training_measurements_and_media_counts(self):
        start = HTML.index("function getPlayerDossierSummary()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        for token in ("matchCount:", "reviewedMatchCount:", "trainingCount:", "trainingMinutes:", "measureCount:", "formCount:", "clipCount:", "latestMeasures"):
            self.assertIn(token, fn)

    def test_stage20_dossier_displays_strengths_remaining_issues_and_insufficient_data(self):
        start = HTML.index("function renderPlayerDossier()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        for token in ("確認できた強み", "残る課題・重点確認", "評価データがまだありません", "課題なしとは判定しません", "playerDossier"):
            self.assertIn(token, fn)

    def test_stage20_monthly_report_integrates_same_month_match_training_and_measure_counts(self):
        start = HTML.index("function renderMonthlyGrowthReport()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("host.innerHTML=monthlyIntegrated+", fn)
        for token in ("monthTrainings", "monthMatches", "monthReviewed", "monthMeasureCount", "monthMinutes", "monthlyIntegrated"):
            self.assertIn(token, fn)

    def test_stage20_player_dossier_is_rendered_with_growth_dashboard(self):
        self.assertIn('id="playerDossier"', HTML)
        self.assertIn("renderPlayerDossier();", HTML)

    def test_stage20_backup_restore_and_saved_video_playback_contracts_remain(self):
        for token in ("actual.toLowerCase()!==String(parsed.stateSha256).toLowerCase()", "state=previousState", "await compareVideoBlobs(verified.blob,restoredFile)", "URL.createObjectURL(saved.blob)", "matchVideo.onloadeddata", "formVideo.onloadeddata"):
            self.assertIn(token, HTML)

    def test_stage20_dossier_filters_measurements_to_valid_iso_dates(self):
        start = HTML.index("function getPlayerDossierSummary()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("latestMeasures=metricTypes.map", fn)
        self.assertIn("Number.isFinite(Number(item.value))", fn)
        self.assertIn("item.date||''", fn)

    def test_stage20_monthly_summary_is_scoped_to_monthly_report_not_player_dossier(self):
        dossier_start = HTML.index("function renderPlayerDossier()")
        monthly_start = HTML.index("function renderMonthlyGrowthReport()")
        decision_start = HTML.index("function getDecisionGrowthSeries()")
        dossier = HTML[dossier_start:monthly_start]
        monthly = HTML[monthly_start:decision_start]
        self.assertNotIn("monthlyIntegrated", dossier)
        self.assertIn("host.innerHTML=monthlyIntegrated+", monthly)


    def test_stage21_growth_goal_linkage_uses_only_manual_goal_and_exact_training_links(self):
        start = HTML.index("function getGrowthGoalTrainingLinkage()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("goal.source!=='manual-reviewed-match-growth'", fn)
        self.assertIn("item.sourceMatch?.growthGoalId===goal.id", fn)
        self.assertIn("getCompletedTrainingStepIndexes", fn)

    def test_stage21_manual_match_goal_creates_persisted_plan_and_rolls_back(self):
        start = HTML.index("function applyMatchGrowthGoal(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("getMatchGrowthRecommendations()", fn)
        self.assertIn("source:'manual-reviewed-match-growth'", fn)
        self.assertIn("state.settings.growthGoalPlan", fn)
        self.assertIn("if(!persist())", fn)
        self.assertIn("元の目標を維持しています", fn)

    def test_stage21_weekly_training_session_keeps_goal_identity(self):
        start = HTML.index("function applyWeeklyCoachSession(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("pendingTrainingSource?.matchGrowthGoal", fn)
        self.assertIn("growthGoalId", fn)
        self.assertIn("state.settings?.growthGoalPlan?.id", fn)

    def test_stage21_goal_linkage_is_rendered_in_growth_dashboard(self):
        self.assertIn('id="growthGoalTrainingLinkage"', HTML)
        self.assertIn("renderGrowthGoalTrainingLinkage();", HTML)
        self.assertIn("updateGrowthGoalStatus(", HTML)
        self.assertIn("この目標を達成として記録", HTML)
        self.assertIn("技術向上や試合での成功を自動判定するものではありません", HTML)

    def test_stage21_goal_status_save_failure_restores_previous_goal(self):
        start = HTML.index("function updateGrowthGoalStatus(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("const previous={...current}", fn)
        self.assertIn("if(!persist())", fn)
        self.assertIn("state.settings.growthGoalPlan=previous", fn)
        self.assertIn("delete state.settings.nextMatchGoal", fn)
        self.assertIn("previousNextGoal", fn)

    def test_stage21_saved_training_record_retains_exact_growth_goal_id(self):
        start = HTML.index("function saveTraining()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("const source=pendingTrainingSource?{...pendingTrainingSource}:null", fn)
        self.assertIn("sourceMatch:source", fn)
        self.assertIn("state.trainings.unshift(record)", fn)
        self.assertIn("if(!persist())", fn)

    def test_stage21_each_new_goal_gets_a_distinct_identity(self):
        self.assertIn("const goalId='growth-'+Date.now()", HTML)
        self.assertIn("growthGoalPlan={id:goalId", HTML)


    def test_stage22_postmatch_goal_review_requires_exact_goal_id_manual_identity_and_manual_assessment(self):
        start = HTML.index("function getGrowthGoalPostMatchReview(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        for token in ("ev.goalEvidenceRelation==='related'", "ev.growthGoalId||'')===String(goal.id)", "isManuallyReviewedMatchEvent(ev)", "ev.reviewSource==='manual'", "ev.assessmentSource==='manual'", "ev.manualGrowthFocus===goal.growthFocus", "String(match.date)>String(goal.date||'')"):
            self.assertIn(token, fn)

    def test_stage22_insufficient_postmatch_evidence_stays_unconfirmed(self):
        start = HTML.index("function getGrowthGoalPostMatchReview(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("if(assessed.length<2)return {status:'未確認'", fn)
        self.assertIn("手動評価が2場面未満のため判定を保留", fn)

    def test_stage22_manual_goal_relation_requires_confirmed_player_and_matching_focus(self):
        start = HTML.index("function saveMatchEventEdits(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("relation==='related'", fn)
        self.assertIn("review!=='陸玖'", fn)
        self.assertIn("read('manualGrowthFocus')!==goal.growthFocus", fn)
        self.assertIn("ev.growthGoalId=relation==='related'?goal.id:null", fn)

    def test_stage22_goal_review_dashboard_is_rendered_and_labels_evidence_limits(self):
        self.assertIn('id="growthGoalPostMatchReview"', HTML)
        self.assertIn("renderGrowthGoalPostMatchReview();", HTML)
        self.assertIn("2場面未満は未確認です", HTML)
        self.assertIn("改善判定は技術向上の確定や目標達成を意味しません", HTML)

    def test_stage22_weekly_plan_uses_only_confirmed_postmatch_status(self):
        start = HTML.index("function getWeeklyCoachPlan()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("getGrowthGoalPostMatchReview(state.settings?.growthGoalPlan)", fn)
        self.assertIn("postMatchGoalReview?.status==='継続'", fn)
        self.assertIn("postMatchGoalReview?.status==='改善'", fn)
        self.assertIn("本人確認済みの試合後評価", fn)

    def test_stage22_monthly_report_includes_postmatch_goal_review_summary(self):
        start = HTML.index("function renderMonthlyGrowthReport()")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("getGrowthGoalPostMatchReview(state.settings?.growthGoalPlan,picker.value)", fn)
        self.assertIn("monthlyGoalSummary", fn)
        self.assertIn("host.innerHTML=monthlyIntegrated+monthlyGoalSummary+", fn)

    def test_stage22_video_ai_candidates_without_manual_relation_are_not_counted(self):
        start = HTML.index("function getGrowthGoalPostMatchReview(")
        end = HTML.index("\nfunction ", start + 20)
        fn = HTML[start:end]
        self.assertIn("ev.goalEvidenceRelation==='related'", fn)
        self.assertIn("ev.reviewSource==='manual'", fn)
        self.assertIn("ev.assessmentSource==='manual'", fn)


if __name__ == "__main__":
    unittest.main()
