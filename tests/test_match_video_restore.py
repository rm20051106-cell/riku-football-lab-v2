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


    def test_upload_resume_falls_back_to_persisted_pipeline_fingerprint(self):
        start = self.html.index("async function postMatchJobToAI")
        end = self.html.index("async function pollMatchJobToAI", start)
        handler = self.html[start:end]
        self.assertIn("const previousPipeline=readMatchPipelineState()", handler)
        self.assertIn("uploadFingerprint:null", handler)
        self.assertIn("previousPipeline.uploadFingerprint===fingerprint", handler)
        self.assertIn("uploadFingerprint:fingerprint", handler)
        self.assertIn("pipelineResume?.uploadId", handler)

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


if __name__ == "__main__":
    unittest.main()
