from pathlib import Path
import unittest


class MatchVideoRestoreRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("index.html").read_text(encoding="utf-8")

    def test_pending_video_restore_reads_indexeddb_blob(self):
        self.assertIn("async function restorePendingMatchVideo()", self.html)
        self.assertIn("getClipVideo('__pending_match_video__')", self.html)
        self.assertIn("URL.createObjectURL(saved.blob)", self.html)
        self.assertIn("matchVideo.src=url", self.html)

    def test_analysis_can_resume_without_file_input_after_reload(self):
        start = self.html.index("async function sendMatchToAI()")
        end = self.html.index("function sendFormToAI()", start)
        handler = self.html[start:end]
        self.assertIn("videoFile.files[0]||await pendingMatchSave", handler)
        self.assertIn("getClipVideo('__pending_match_video__')", handler)
        self.assertIn("new File([saved.blob]", handler)
        self.assertIn("await postMatchJobToAI(file,matchAiResult)", handler)

    def test_saved_video_metadata_includes_original_filename_and_timestamp(self):
        start = self.html.index("async function storeClipVideo")
        end = self.html.index("async function getClipVideo", start)
        helper = self.html[start:end]
        self.assertIn("name:file.name", helper)
        self.assertIn("lastModified:file.lastModified||Date.now()", helper)

    def test_restore_is_invoked_during_app_startup(self):
        self.assertIn("load();renderChecks();renderAll();renderMatchPipelineState();", self.html)
        self.assertIn("restorePendingMatchVideo();", self.html)

    def test_last_selected_view_is_persisted_and_restored(self):
        start = self.html.index("function showView(id)")
        end = self.html.index("function inferTrainingFocus", start)
        show_view = self.html[start:end]
        self.assertIn("localStorage.setItem('riku_last_view_v1',String(id))", show_view)
        self.assertIn("safeMatchStorageGet('riku_last_view_v1')==='video'", self.html)
        self.assertIn("showView('video')", self.html)


    def test_safari_bfcache_return_restores_video_workspace_and_job(self):
        self.assertIn("function restoreMatchWorkspaceOnReturn()", self.html)
        self.assertIn("window.addEventListener('pagehide'", self.html)
        self.assertIn("safeMatchStorageSet('riku_last_view_v1','video')", self.html)
        self.assertIn("window.addEventListener('pageshow',event=>", self.html)
        self.assertIn("if(event.persisted)restoreMatchWorkspaceOnReturn()", self.html)
        self.assertIn("pendingMatchRestore=restorePendingMatchVideo()", self.html)
        self.assertIn("pollMatchJobToAI(activeJob,matchAiResult)", self.html)

    def test_visibility_and_focus_return_restore_workspace_without_duplicate_bursts(self):
        self.assertIn("let lastMatchWorkspaceRestoreAt=0", self.html)
        self.assertIn("if(now-lastMatchWorkspaceRestoreAt<2500)return true", self.html)
        self.assertIn("document.addEventListener('visibilitychange'", self.html)
        self.assertIn("if(document.visibilityState==='visible')restoreMatchWorkspaceOnReturn()", self.html)
        self.assertIn("window.addEventListener('focus',()=>restoreMatchWorkspaceOnReturn())", self.html)

    def test_home_shows_recovery_entry_for_pending_video_work(self):
        self.assertIn('id="homeMatchRecovery"', self.html)
        self.assertIn('onclick="returnToMatchWorkspace()"', self.html)
        self.assertIn("function renderHomeMatchRecovery()", self.html)
        self.assertIn("card.hidden=!pending", self.html)
        self.assertIn("function returnToMatchWorkspace()", self.html)
        self.assertIn("renderHomeMatchRecovery();", self.html)

    def test_home_recovery_offers_same_video_reselection_for_pending_upload(self):
        self.assertIn('id="homeMatchReselect"', self.html)
        self.assertIn("const needsReselect=!!pipeline.uploadId&&!activeJob", self.html)
        self.assertIn("if(reselect)reselect.hidden=!needsReselect", self.html)
        self.assertIn("function reselectPendingMatchVideo()", self.html)
        self.assertIn("picker.click()", self.html)

    def test_return_to_match_workspace_waits_for_indexeddb_restore_before_reconnect(self):
        start = self.html.index("async function returnToMatchWorkspace()")
        end = self.html.index("function reselectPendingMatchVideo()", start)
        handler = self.html[start:end]
        self.assertIn("await pendingMatchRestore", handler)
        self.assertLess(handler.index("await pendingMatchRestore"), handler.index("pollMatchJobToAI"))

    def test_recovery_navigation_preserves_pending_video_blob(self):
        start = self.html.index("async function returnToMatchWorkspace()")
        end = self.html.index("function reselectPendingMatchVideo()", start)
        handler = self.html[start:end]
        self.assertNotIn("removeClipVideo", handler)
        self.assertIn("restorePendingMatchVideo()", handler)
        self.assertIn("renderMatchPipelineState()", handler)

    def test_send_match_to_ai_prevents_duplicate_upload_start(self):
        start = self.html.index("async function sendMatchToAI()")
        end = self.html.index("function sendFormToAI()", start)
        handler = self.html[start:end]
        self.assertIn("window.__rikuMatchUploadStarting", handler)
        self.assertIn("window.__rikuMatchUploadStarting=true", handler)
        self.assertIn("window.__rikuMatchUploadStarting=false", handler)
        self.assertIn("finally", handler)
        self.assertIn("await postMatchJobToAI(file,matchAiResult)", handler)

    def test_video_picker_resets_input_to_allow_same_file_reselection(self):
        start = self.html.index("videoFile.addEventListener('change'")
        end = self.html.index("let pendingFormSave", start)
        handler = self.html[start:end]
        self.assertIn("let f=videoFile.files[0]", handler)
        self.assertLess(handler.index("if(!f)return"), handler.index("videoFile.value=''"))
        self.assertIn("pendingMatchSave=storeClipVideo('__pending_match_video__',f)", handler)

    def test_analysis_uses_saved_file_after_picker_value_is_cleared(self):
        start = self.html.index("async function sendMatchToAI()")
        end = self.html.index("function sendFormToAI()", start)
        handler = self.html[start:end]
        self.assertIn("let file=videoFile.files[0]||await pendingMatchSave", handler)
        self.assertIn("getClipVideo('__pending_match_video__')", handler)
        self.assertIn("new File([saved.blob]", handler)

    def test_indexeddb_video_save_rejects_on_transaction_abort(self):
        start = self.html.index("async function storeClipVideo")
        end = self.html.index("async function getClipVideo", start)
        helper = self.html[start:end]
        self.assertIn("tx.onabort", helper)
        self.assertIn("db.close()", helper)
        self.assertIn("動画保存が中断されました", helper)

    def test_indexeddb_video_read_rejects_on_transaction_abort_once(self):
        start = self.html.index("async function getClipVideo")
        end = self.html.index("async function removeClipVideo", start)
        helper = self.html[start:end]
        self.assertIn("let settled=false", helper)
        self.assertIn("const finish=(fn,value)=>{if(settled)return", helper)
        self.assertIn("tx.onabort", helper)
        self.assertIn("動画の読み込みが中断されました", helper)

    def test_indexeddb_video_read_resolves_only_after_transaction_completion(self):
        start = self.html.index("async function getClipVideo")
        end = self.html.index("async function removeClipVideo", start)
        helper = self.html[start:end]
        self.assertIn("req.onsuccess=()=>{result=req.result||null}", helper)
        self.assertIn("tx.oncomplete=()=>finish(resolve,result)", helper)

    def test_pending_video_restore_surfaces_storage_failure_to_user(self):
        start = self.html.index("async function restorePendingMatchVideo()")
        end = self.html.index("async function sendMatchToAI()", start)
        helper = self.html[start:end]
        self.assertIn("端末内動画の復元に失敗しました", helper)
        self.assertIn("元の動画を選び直してください", helper)

    def test_pending_video_restore_rejects_empty_or_non_blob_payload(self):
        start = self.html.index("async function restorePendingMatchVideo()")
        end = self.html.index("async function sendMatchToAI()", start)
        helper = self.html[start:end]
        self.assertIn("saved.blob instanceof Blob", helper)
        self.assertIn("saved.blob.size<=0", helper)
        self.assertIn("端末内の動画データが空か読み取れません", helper)

    def test_pending_restore_does_not_overwrite_a_newer_video_selection(self):
        self.assertIn("let matchVideoSelectionVersion=0", self.html)
        start = self.html.index("async function restorePendingMatchVideo()")
        end = self.html.index("async function sendMatchToAI()", start)
        restore = self.html[start:end]
        self.assertIn("const selectionVersion=matchVideoSelectionVersion", restore)
        self.assertIn("if(selectionVersion!==matchVideoSelectionVersion)return false", restore)
        start = self.html.index("videoFile.addEventListener('change'")
        self.assertIn("matchVideoSelectionVersion++", self.html[start:start+180])

    def test_upload_resume_falls_back_to_persisted_pipeline_fingerprint(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("const previousPipeline=readMatchPipelineState()", handler)
        self.assertIn("uploadFingerprint:null", handler)
        self.assertIn("previousPipeline.uploadFingerprint===fingerprint", handler)
        self.assertIn("uploadFingerprint:fingerprint", handler)
        self.assertIn("pipelineResume?.uploadId", handler)

    def test_upload_failure_keeps_upload_session_for_retry(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        catch = handler[handler.rfind("}catch(e){"):]
        self.assertIn("stageLabel:'通信・処理エラー／再接続待ち'", catch)
        self.assertIn("同じ動画を選ぶと受信済み分割から再開できます", handler)
        self.assertNotIn("uploadId:null", catch)

    def test_match_upload_does_not_delete_local_pending_video(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertNotIn("removeClipVideo('__pending_match_video__')", handler)
        self.assertIn("updateMatchPipelineState({stageLabel:'解析ジョブ受付完了'", handler)

    def test_analysis_job_id_is_persisted_before_polling_starts(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        persist = handler.index("localStorage.setItem('riku_active_match_job_v1',jobId)")
        poll = handler.index("pollMatchJobToAI(jobId,resultElement)", persist)
        self.assertLess(persist, poll)

    def test_stage100_long_video_recovery_invariants_are_present_together(self):
        self.assertIn("indexeddb", self.html.lower())
        self.assertIn("function reselectPendingMatchVideo()", self.html)
        self.assertIn("window.__rikuMatchUploadStarting", self.html)
        self.assertIn("matchVideoSelectionVersion", self.html)
        self.assertIn("saved.blob.size<=0", self.html)
        self.assertIn("tx.oncomplete=()=>finish(resolve,result)", self.html)
        self.assertIn("stageLabel:'通信・処理エラー／再接続待ち'", self.html)
        self.assertIn("localStorage.setItem('riku_active_match_job_v1',jobId)", self.html)
        self.assertIn("renderHomeMatchRecovery();", self.html)

    def test_startup_video_restore_is_awaitable_before_analysis(self):
        self.assertIn("pendingMatchRestore=Promise.resolve(false)", self.html)
        self.assertIn("pendingMatchRestore=restorePendingMatchVideo();", self.html)
        start = self.html.index("async function sendMatchToAI()")
        end = self.html.index("function sendFormToAI()", start)
        handler = self.html[start:end]
        self.assertIn("await pendingMatchRestore", handler)
        self.assertIn("getClipVideo('__pending_match_video__')", handler)

    def test_match_history_persists_stable_job_id(self):
        start = self.html.index("function saveMatchScanResult")
        end = self.html.index("function formatMatchTime", start)
        save = self.html[start:end]
        self.assertIn("jobId:result.job_id||null", save)
        self.assertIn("String(x.jobId||'')===stableJobId", save)

    def test_upload_rejects_empty_video_before_network_requests(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("!Number.isFinite(file.size)||file.size<=0", handler)
        self.assertLess(handler.index("file.size<=0"), handler.index("fetch(u+'/health'"))

    def test_upload_chunk_geometry_must_be_positive_and_safe(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("Number.isSafeInteger(chunkCount)", handler)
        self.assertIn("chunkCount<1", handler)

    def test_resume_ignores_invalid_server_chunk_indexes(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("Array.isArray(session.received_chunks)", handler)
        self.assertIn("Number.isInteger(part)&&part>=0&&part<chunkCount", handler)

    def test_resumed_upload_id_is_saved_before_chunk_transfer(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        persist = handler.index("stageLabel:'アップロード再開準備完了'")
        transfer = handler.index("for(let part=0;part<chunkCount;part++)")
        self.assertLess(persist, transfer)
        self.assertIn("uploadFingerprint:fingerprint", handler[persist:transfer])
    def test_complete_response_requires_nonempty_string_job_id(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("typeof created.job_id!=='string'", handler)
        self.assertIn("!created.job_id.trim()", handler)
    def test_retryable_error_keeps_resumable_upload_metadata(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        catch = handler[handler.rfind("}catch(e){"):]
        self.assertIn("uploadId:uploadId||readMatchPipelineState().uploadId||null", catch)
        self.assertIn("uploadFingerprint:readMatchPipelineState().uploadFingerprint||null", catch)
    def test_completed_upload_resume_requires_valid_job_id(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("session.completed&&typeof session.job_id==='string'&&session.job_id.trim()", handler)
    def test_resume_hash_metadata_must_be_an_object_not_array(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("typeof session.received_chunk_sha256==='object'", handler)
        self.assertIn("!Array.isArray(session.received_chunk_sha256)", handler)
    def test_upload_error_refreshes_recovery_panel_immediately(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        catch = handler[handler.rfind("}catch(e){"):]
        self.assertIn("renderMatchPipelineState();", catch)

if __name__ == "__main__":
    unittest.main()
