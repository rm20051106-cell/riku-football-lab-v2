import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from upload_integrity import verify_uploaded_chunks, build_upload_resume_state, reconcile_uploaded_chunks


class UploadIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "video.mp4"
        self.data = b"abcdefghij"
        self.path.write_bytes(self.data)
        self.chunks = {
            "0": {"size_bytes": 4, "sha256": hashlib.sha256(b"abcd").hexdigest()},
            "1": {"size_bytes": 4, "sha256": hashlib.sha256(b"efgh").hexdigest()},
            "2": {"size_bytes": 2, "sha256": hashlib.sha256(b"ij").hexdigest()},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resume_state_reports_out_of_order_chunks_and_partial_tail(self):
        state = build_upload_resume_state(10, 4, {"2": self.chunks["2"], "0": self.chunks["0"]})
        self.assertEqual(state["total_chunks"], 3)
        self.assertEqual(state["received_chunks"], [0, 2])
        self.assertEqual(state["received_chunk_sha256"], {
            "0": self.chunks["0"]["sha256"], "2": self.chunks["2"]["sha256"]
        })
        self.assertEqual(state["missing_chunks"], [1])
        self.assertEqual(state["received_bytes"], 6)
        self.assertEqual(state["confirmed_percent"], 60)

    def test_resume_state_reports_complete_upload(self):
        state = build_upload_resume_state(10, 4, self.chunks)
        self.assertEqual(state["missing_chunks"], [])
        self.assertEqual(state["received_bytes"], 10)
        self.assertEqual(state["confirmed_percent"], 100)

    def test_resume_state_rejects_invalid_chunk_metadata(self):
        with self.assertRaisesRegex(ValueError, "metadata size"):
            build_upload_resume_state(10, 4, {"2": {"size_bytes": 4, "sha256": "0" * 64}})

    def test_resume_state_rejects_missing_sha256(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_upload_resume_state(10, 4, {"0": {"size_bytes": 4}})

    def test_resume_state_rejects_malformed_sha256(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_upload_resume_state(10, 4, {"0": {"size_bytes": 4, "sha256": "not-a-hash"}})

    def test_valid_chunks_pass_streaming_verification(self):
        verify_uploaded_chunks(str(self.path), 10, 4, self.chunks)

    def test_modified_chunk_is_rejected(self):
        self.path.write_bytes(b"abcdEfghij")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            verify_uploaded_chunks(str(self.path), 10, 4, self.chunks)

    def test_verification_rejects_malformed_sha256_metadata(self):
        invalid = dict(self.chunks)
        invalid["1"] = {"size_bytes": 4, "sha256": "bad"}
        with self.assertRaisesRegex(ValueError, "invalid chunk SHA-256"):
            verify_uploaded_chunks(str(self.path), 10, 4, invalid)

    def test_ensure_upload_file_recreates_missing_sparse_file(self):
        missing_path = self.path.with_name("recreated.mp4")
        self.assertTrue(ensure_upload_file(str(missing_path), 12345))
        self.assertEqual(missing_path.stat().st_size, 12345)
        self.assertFalse(ensure_upload_file(str(missing_path), 12345))
        self.assertEqual(missing_path.stat().st_size, 12345)

    def test_ensure_upload_file_rejects_path_outside_temp_directory(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            ensure_upload_file("/etc/riku-upload.mp4", 100)

    def test_reconcile_detects_corrupted_chunk_as_resend_candidate(self):
        self.path.write_bytes(b"abcdEFghij")
        self.assertEqual(
            reconcile_uploaded_chunks(str(self.path), 10, 4, self.chunks), [1]
        )

    def test_reconcile_accepts_valid_chunks_and_partial_tail(self):
        self.assertEqual(
            reconcile_uploaded_chunks(str(self.path), 10, 4, {
                "0": self.chunks["0"], "2": self.chunks["2"]
            }), []
        )

    def test_reconcile_marks_chunks_missing_when_temp_file_is_gone(self):
        missing_path = self.path.with_name("missing.mp4")
        self.assertEqual(
            reconcile_uploaded_chunks(str(missing_path), 10, 4, {
                "0": self.chunks["0"], "2": self.chunks["2"]
            }), [0, 2]
        )

    def test_wrong_file_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "size"):
            verify_uploaded_chunks(str(self.path), 11, 4, self.chunks)

    def test_missing_chunk_metadata_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            verify_uploaded_chunks(str(self.path), 10, 4, {"0": self.chunks["0"]})


if __name__ == "__main__":
    unittest.main()
