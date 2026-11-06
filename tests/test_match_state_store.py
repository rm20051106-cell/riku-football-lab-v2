import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import job_store


class MatchStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "state.sqlite3")
        self.old_path = os.environ.get("RIKU_STATE_DB")
        os.environ["RIKU_STATE_DB"] = self.db_path
        job_store.init_state_store()

    def tearDown(self):
        if self.old_path is None:
            os.environ.pop("RIKU_STATE_DB", None)
        else:
            os.environ["RIKU_STATE_DB"] = self.old_path
        self.temp_dir.cleanup()

    def test_upload_completion_is_idempotent_and_reuses_original_job(self):
        first, created_first = job_store.create_match_job_for_upload("upload-once", {
            "job_id": "job-first", "status": "queued", "progress": 0,
        })
        second, created_second = job_store.create_match_job_for_upload("upload-once", {
            "job_id": "job-second", "status": "queued", "progress": 0,
        })
        self.assertEqual(first, "job-first")
        self.assertEqual(second, "job-first")
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(job_store.get_match_upload_completion("upload-once"), "job-first")
        self.assertIn("job-first", job_store.load_match_jobs())
        self.assertNotIn("job-second", job_store.load_match_jobs())

    def test_job_survives_store_reload_and_updates(self):
        job_store.save_match_job("job-1", {
            "job_id": "job-1", "status": "processing", "progress": 42,
            "stage": "動画全体をスキャン中", "result": None,
        })
        restored = job_store.load_match_jobs()
        self.assertEqual(restored["job-1"]["progress"], 42)
        job_store.save_match_job("job-1", {
            "job_id": "job-1", "status": "completed", "progress": 100,
            "result": {"summary": {"sampled_frames": 300}},
        })
        restored = job_store.load_match_jobs()
        self.assertEqual(restored["job-1"]["status"], "completed")
        self.assertEqual(restored["job-1"]["result"]["summary"]["sampled_frames"], 300)

    def test_upload_session_and_chunk_hashes_survive_reload(self):
        video_path = str(Path(self.temp_dir.name) / "upload.mp4")
        Path(video_path).write_bytes(b"video")
        session = {
            "upload_id": "upload-1", "filename": "match.mp4",
            "size_bytes": 5, "chunk_size_bytes": 4,
            "path": video_path, "chunks": {"0": {"sha256": "abc", "size_bytes": 4}},
        }
        job_store.save_match_upload("upload-1", session)
        restored = job_store.load_match_uploads()
        self.assertEqual(restored["upload-1"]["chunks"]["0"]["sha256"], "abc")

    def test_missing_upload_file_session_is_restored_for_chunk_recovery(self):
        missing_path = str(Path(self.temp_dir.name) / "missing.mp4")
        job_store.save_match_upload("upload-missing", {
            "upload_id": "upload-missing", "path": missing_path,
            "size_bytes": 100, "chunk_size_bytes": 40, "chunks": {"0": {"sha256": "a" * 64, "size_bytes": 40}},
        })
        restored = job_store.load_match_uploads()
        self.assertIn("upload-missing", restored)
        self.assertEqual(restored["upload-missing"]["path"], missing_path)
        self.assertFalse(Path(missing_path).exists())

    def test_upload_session_can_be_deleted(self):
        job_store.save_match_upload("upload-delete", {"upload_id": "upload-delete", "path": "unused"})
        job_store.delete_match_upload("upload-delete")
        self.assertNotIn("upload-delete", job_store.load_match_uploads())

    def test_expired_incomplete_upload_is_removed_but_recent_upload_is_kept(self):
        expired_path = str(Path(self.temp_dir.name) / "expired.mp4")
        recent_path = str(Path(self.temp_dir.name) / "recent.mp4")
        Path(expired_path).write_bytes(b"old")
        Path(recent_path).write_bytes(b"new")
        job_store.save_match_upload("upload-expired", {"upload_id": "upload-expired", "path": expired_path, "chunks": {}})
        job_store.save_match_upload("upload-recent", {"upload_id": "upload-recent", "path": recent_path, "chunks": {}})
        with job_store._connect() as connection:
            connection.execute("UPDATE match_uploads SET updated_at = datetime('now', '-48 hours') WHERE upload_id = ?", ("upload-expired",))
        paths = job_store.cleanup_expired_match_uploads(24)
        self.assertEqual(paths, [expired_path])
        restored = job_store.load_match_uploads()
        self.assertNotIn("upload-expired", restored)
        self.assertIn("upload-recent", restored)
        self.assertTrue(Path(expired_path).exists())


if __name__ == "__main__":
    unittest.main()
