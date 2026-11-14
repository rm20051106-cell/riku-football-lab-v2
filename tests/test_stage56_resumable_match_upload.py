import ast
import hashlib
import json
import os
import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)




def load_session_helpers(directory):
    names = {"match_upload_manifest_path", "persist_match_upload_state",
             "restore_match_upload_sessions"}
    nodes = [item for item in TREE.body
             if isinstance(item, ast.FunctionDef) and item.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "Path": pathlib.Path, "os": os, "json": json, "time": time,
        "MATCH_UPLOAD_SESSION_DIR": pathlib.Path(directory),
        "MATCH_UPLOAD_SESSION_TTL_SECONDS": 24 * 60 * 60,
        "MAX_MATCH_UPLOAD_MB": 500,
    }
    exec(compile(module, "<stage56-session>", "exec"), namespace)
    return namespace


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


    def test_upload_session_manifest_restores_after_process_restart_and_truncates_uncommitted_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            helpers = load_session_helpers(directory)
            with tempfile.NamedTemporaryFile(delete=False) as video:
                video.write(b"committed")
                video.write(b"uncommitted-tail")
                video_path = video.name
            state = {
                "path": video_path, "filename": "match.mp4", "total_size": 100,
                "duration_seconds": 900.0, "chunk_size": 4, "total_chunks": 25,
                "next_chunk": 2, "received_bytes": 9, "chunk_hashes": {0: "abc", 1: "def"},
                "jersey_numbers": "10,74",
            }
            helpers["persist_match_upload_state"]("recoverable-upload", state)
            restored = helpers["restore_match_upload_sessions"]()
            self.assertIn("recoverable-upload", restored)
            self.assertEqual(restored["recoverable-upload"]["next_chunk"], 2)
            self.assertEqual(restored["recoverable-upload"]["chunk_hashes"], {0: "abc", 1: "def"})
            with open(video_path, "rb") as saved:
                self.assertEqual(saved.read(), b"committed")
            os.remove(video_path)

    def test_upload_status_endpoint_and_manifest_cleanup_are_wired(self):
        self.assertIn('@app.get("/analyze/match/uploads/{upload_id}")', SOURCE)
        self.assertIn('"next_chunk": upload_state["next_chunk"]', SOURCE)
        self.assertIn("persist_match_upload_state(upload_id, match_uploads[upload_id])", SOURCE)
        self.assertIn("match_upload_manifest_path(upload_id).unlink(missing_ok=True)", SOURCE)

    def test_frontend_persists_upload_id_and_resumes_from_server_next_chunk(self):
        self.assertIn('async function getPendingMatchUpload()', HTML)
        self.assertIn('async function savePendingMatchUpload(record)', HTML)
        self.assertIn('async function clearPendingMatchUpload()', HTML)
        self.assertIn('saved.sourceKey===identity.sourceKey', HTML)
        self.assertIn("method:'GET',credentials:'omit',cache:'no-store'", HTML)
        self.assertIn('nextChunk=Number(status.next_chunk)', HTML)
        self.assertIn('中断しても同じ動画を再選択すると続きから再開できます', HTML)
        self.assertIn('clearPendingMatchUpload()', HTML)
        self.assertIn('return body', HTML)
        self.assertIn("getClipVideo('__pending_match_video__')", HTML)
        self.assertIn('lastModified:Number(file.lastModified||0)', HTML)
        upload = HTML[HTML.index('async function uploadMatchVideoInChunks'):HTML.index('async function postMatchJobToAI')]
        self.assertNotIn('method:\'DELETE\'', upload)

    def test_api_and_frontend_use_chunked_upload_not_single_large_post(self):
        self.assertIn("/analyze/match/uploads", SOURCE)
        self.assertIn("/analyze/match/uploads", HTML)
        self.assertIn("uploadMatchVideoInChunks(file", HTML)
        self.assertIn("attempt<=3", HTML)
        self.assertIn("AbortController", HTML)
        self.assertIn("/analyze/match/jobs", SOURCE)
        self.assertIn('"PUT", "DELETE"', SOURCE)


    def test_analysis_job_status_polling_retries_transient_failures_with_timeout(self):
        helper = HTML.split("async function fetchMatchJobStatusWithRetry", 1)[1].split(
            "async function postMatchJobToAI", 1
        )[0]
        self.assertIn("retryLimit", helper)
        self.assertIn("AbortController", helper)
        self.assertIn("timeoutMs", helper)
        self.assertIn("response.status>=400&&response.status<500", helper)
        self.assertIn("retryDelayMs*attempt", helper)
        self.assertIn("解析ジョブ情報は端末に保持しています", helper)
        polling = HTML.split("async function postMatchJobToAI", 1)[1].split(
            "async function resumePendingMatchJob", 1
        )[0]
        self.assertIn("fetchMatchJobStatusWithRetry(u,jobId)", polling)
        self.assertNotIn("const statusResponse=await fetch(u+'/analyze/jobs/'", polling)

    def test_frontend_persists_analysis_job_and_resumes_after_reload(self):
        self.assertIn("async function getPendingMatchJob()", HTML)
        self.assertIn("async function savePendingMatchJob(record)", HTML)
        self.assertIn("async function clearPendingMatchJob()", HTML)
        self.assertIn("await savePendingMatchJob({jobId:body.job_id", HTML)
        self.assertIn("async function resumePendingMatchJob()", HTML)
        self.assertIn("setTimeout(()=>resumePendingMatchJob(),800)", HTML)
        self.assertIn("postMatchJobToAI(null,resultElement,{...pending,apiBaseUrl:savedBase})", HTML)
        self.assertIn("existingJob?.apiBaseUrl||getApiUrl()", HTML)
        self.assertIn("await clearPendingMatchJob()", HTML)
        completed_branch = HTML.split("if(status.status==='completed'){", 1)[1].split("return;", 1)[0]
        self.assertNotIn("clearPendingMatchJob()", completed_branch)
        saved_result = HTML.split("async function saveMatchScanResult()", 1)[1].split("function formatMatchTime", 1)[0]
        self.assertIn("if(!persist())", saved_result)
        self.assertIn("await clearPendingMatchJob()", saved_result)

    def test_upload_chunk_size_matches_backend_12mb_and_retry_timeout_contract(self):
        self.assertIn("MATCH_UPLOAD_CHUNK_BYTES = 12 * 1024 * 1024", SOURCE)
        self.assertIn("chunkSize=Number(created.chunk_size)||chunkSizeDefault", HTML)
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("chunk_size: 12 * 1024 * 1024", retry_test)
        self.assertIn("new Uint8Array(12 * 1024 * 1024 + 1)", retry_test)
        upload = HTML[HTML.index("async function uploadMatchVideoInChunks"):HTML.index("async function fetchMatchJobStatusWithRetry")]
        self.assertIn("attempt<=3", upload)
        self.assertIn("setTimeout(()=>controller.abort(),120000)", upload)
        self.assertIn("method:'GET',credentials:'omit',cache:'no-store'", upload)
        self.assertIn("nextChunk=Number(current.next_chunk)", upload)

    def test_resume_detects_local_server_checkpoint_mismatch_and_syncs_to_server(self):
        upload = HTML[HTML.index("async function uploadMatchVideoInChunks"):HTML.index("async function fetchMatchJobStatusWithRetry")]
        self.assertIn("const serverNextChunk=Number(status.next_chunk)", upload)
        self.assertIn("const localNextChunk=Number(saved.nextChunk)", upload)
        self.assertIn("checkpointMismatch=Number.isInteger(localNextChunk)&&localNextChunk!==serverNextChunk", upload)
        self.assertIn("サーバー側の受信位置を優先します", upload)
        self.assertIn("await persistResume({...identity,uploadId:session.upload_id,chunkSize,totalChunks:total,nextChunk,createdAt:saved.createdAt||Date.now()})", upload)
        self.assertIn("serverNextChunk>serverTotalChunks", upload)

    def test_browser_retry_suite_covers_timeout_and_both_checkpoint_drift_directions(self):
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("def test_timeout_aborts_chunk_and_retries_after_server_reconciliation", retry_test)
        self.assertIn("def test_server_checkpoint_overrides_stale_indexeddb_checkpoint", retry_test)
        self.assertIn("local-behind", retry_test)
        self.assertIn("local-ahead", retry_test)
        self.assertIn("checkpointAtFirstPut", retry_test)
        self.assertIn("timedOut", retry_test)


if __name__ == "__main__":
    unittest.main()
