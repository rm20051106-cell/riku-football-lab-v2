import ast
import hashlib
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_append_helper():
    node = next(item for item in TREE.body if isinstance(item, ast.FunctionDef)
                and item.name == "append_match_upload_chunk")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"hashlib": hashlib}
    exec(compile(module, "<stage56-upload>", "exec"), namespace)
    return namespace["append_match_upload_chunk"]


class Stage56ResumableMatchUploadTests(unittest.TestCase):
    def test_ordered_chunks_reassemble_exact_original_bytes(self):
        append = load_append_helper()
        payload = b"abcdefghij"
        with tempfile.NamedTemporaryFile() as tmp:
            state = {"path": tmp.name, "chunk_size": 4, "total_size": len(payload)}
            self.assertTrue(append(state, 0, payload[:4]))
            self.assertTrue(append(state, 1, payload[4:8]))
            self.assertTrue(append(state, 2, payload[8:]))
            with open(tmp.name, "rb") as source:
                self.assertEqual(source.read(), payload)
            self.assertEqual(state["received_bytes"], len(payload))
            self.assertEqual(state["next_chunk"], 3)

    def test_identical_retry_is_idempotent(self):
        append = load_append_helper()
        with tempfile.NamedTemporaryFile() as tmp:
            state = {"path": tmp.name, "chunk_size": 4, "total_size": 4}
            self.assertTrue(append(state, 0, b"same"))
            self.assertFalse(append(state, 0, b"same"))
            with open(tmp.name, "rb") as source:
                self.assertEqual(source.read(), b"same")

    def test_wrong_order_or_different_duplicate_is_rejected(self):
        append = load_append_helper()
        with tempfile.NamedTemporaryFile() as tmp:
            state = {"path": tmp.name, "chunk_size": 4, "total_size": 8}
            with self.assertRaises(ValueError):
                append(state, 1, b"data")
            append(state, 0, b"data")
            with self.assertRaises(ValueError):
                append(state, 0, b"else")

    def test_invalid_chunk_length_is_rejected(self):
        append = load_append_helper()
        with tempfile.NamedTemporaryFile() as tmp:
            state = {"path": tmp.name, "chunk_size": 4, "total_size": 6}
            with self.assertRaises(ValueError):
                append(state, 0, b"bad")

    def test_api_and_frontend_use_chunked_upload_not_single_large_post(self):
        self.assertIn("/analyze/match/uploads", SOURCE)
        self.assertIn("/analyze/match/uploads", HTML)
        self.assertIn("uploadMatchVideoInChunks(file", HTML)
        self.assertIn("attempt<=3", HTML)
        self.assertIn("AbortController", HTML)
        self.assertIn("/analyze/match/jobs", SOURCE)
        self.assertIn('"PUT", "DELETE"', SOURCE)


if __name__ == "__main__":
    unittest.main()
