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
        end = self.html.index("async function sendFormToAI()", start)
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
        self.assertIn("load();renderChecks();renderAll();renderMatchPipelineState();\nrestorePendingMatchVideo();", self.html)


if __name__ == "__main__":
    unittest.main()
