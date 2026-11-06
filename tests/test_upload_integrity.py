import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from upload_integrity import verify_uploaded_chunks


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

    def test_valid_chunks_pass_streaming_verification(self):
        verify_uploaded_chunks(str(self.path), 10, 4, self.chunks)

    def test_modified_chunk_is_rejected(self):
        self.path.write_bytes(b"abcdEfghij")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            verify_uploaded_chunks(str(self.path), 10, 4, self.chunks)

    def test_wrong_file_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "size"):
            verify_uploaded_chunks(str(self.path), 11, 4, self.chunks)

    def test_missing_chunk_metadata_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            verify_uploaded_chunks(str(self.path), 10, 4, {"0": self.chunks["0"]})


if __name__ == "__main__":
    unittest.main()
