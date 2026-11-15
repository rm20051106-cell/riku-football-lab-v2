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


def load_upload_status_helper(upload_id, upload_state):
    node = next(item for item in TREE.body if isinstance(item, ast.FunctionDef)
                and item.name == "get_match_upload_status")

    class HTTPExceptionStub(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"match_uploads": {upload_id: upload_state}, "HTTPException": HTTPExceptionStub}
    exec(compile(module, "<stage56-upload-status>", "exec"), namespace)
    return namespace["get_match_upload_status"](upload_id)


def load_append_helper():
    node = next(item for item in TREE.body if isinstance(item, ast.FunctionDef)
                and item.name == "append_match_upload_chunk")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"hashlib": hashlib}
    exec(compile(module, "<stage56-upload>", "exec"), namespace)
    return namespace["append_match_upload_chunk"]


def load_job_restore_helpers(directory):
    names = {"match_job_manifest_path", "restore_match_jobs"}
    nodes = [item for item in TREE.body
             if isinstance(item, ast.FunctionDef) and item.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "Path": pathlib.Path, "os": os, "json": json,
        "MATCH_UPLOAD_SESSION_DIR": pathlib.Path(directory),
    }
    exec(compile(module, "<stage56-job-restore>", "exec"), namespace)
    return namespace


def load_resume_interrupted_jobs_helper(match_jobs, thread_factory, persisted):
    node = next(item for item in TREE.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "resume_interrupted_match_jobs")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {
        "match_jobs": match_jobs,
        "threading": type("ThreadingStub", (), {"Thread": thread_factory}),
        "os": os,
        "persist_match_job_state": lambda job_id, job: persisted.append((job_id, dict(job))),
        "run_match_job": lambda *args: None,
    }
    exec(compile(module, "<stage56-resume-jobs>", "exec"), namespace)
    return namespace["resume_interrupted_match_jobs"]


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

    def test_interrupted_jobs_restore_from_manifests_and_missing_sources_fail_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            helpers = load_job_restore_helpers(directory)
            source = pathlib.Path(directory) / "recoverable.mp4"
            source.write_bytes(b"synthetic-video")
            queued = {
                "job_id": "queued-job", "status": "queued", "progress": 42,
                "stage": "途中", "source_path": str(source), "jersey_numbers": "10,74",
            }
            processing = {
                "job_id": "processing-job", "status": "processing", "progress": 65,
                "stage": "解析中", "source_path": str(pathlib.Path(directory) / "missing.mp4"),
            }
            helpers["match_job_manifest_path"]("queued-job").write_text(
                json.dumps(queued), encoding="utf-8"
            )
            helpers["match_job_manifest_path"]("processing-job").write_text(
                json.dumps(processing), encoding="utf-8"
            )
            corrupt_path = helpers["match_job_manifest_path"]("corrupt-job")
            corrupt_path.write_text("{invalid-json", encoding="utf-8")

            restored = helpers["restore_match_jobs"]()

            self.assertEqual(restored["queued-job"]["status"], "queued")
            self.assertEqual(restored["queued-job"]["progress"], 0)
            self.assertEqual(restored["queued-job"]["stage"], "再起動後の解析再開待ち")
            self.assertEqual(restored["processing-job"]["status"], "failed")
            self.assertIn("元動画の一時ファイルが見つかりません", restored["processing-job"]["error"])
            self.assertNotIn("corrupt-job", restored)
            self.assertFalse(corrupt_path.exists())

    def test_startup_resume_requeues_only_jobs_with_existing_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "available.mp4"
            source.write_bytes(b"synthetic-video")
            jobs = {
                "available-job": {
                    "status": "queued", "source_path": str(source), "jersey_numbers": "10,74",
                },
                "missing-job": {
                    "status": "queued", "source_path": str(pathlib.Path(directory) / "missing.mp4"),
                },
            }
            started = []
            persisted = []

            class FakeThread:
                def __init__(self, target, args, daemon):
                    self.target, self.args, self.daemon = target, args, daemon

                def start(self):
                    started.append((self.target, self.args, self.daemon))

            resume = load_resume_interrupted_jobs_helper(jobs, FakeThread, persisted)
            resume()

            self.assertEqual(len(started), 1)
            self.assertEqual(started[0][1], ("available-job", str(source), "10,74"))
            self.assertTrue(started[0][2])
            self.assertEqual(jobs["missing-job"]["status"], "failed")
            self.assertTrue(any(job_id == "missing-job" for job_id, _ in persisted))
            self.assertIn('@app.on_event("startup")', SOURCE)
            self.assertIn("resume_interrupted_match_jobs()", SOURCE)

    def test_upload_status_endpoint_and_manifest_cleanup_are_wired(self):
        self.assertIn('@app.get("/analyze/match/uploads/{upload_id}")', SOURCE)
        self.assertIn('"next_chunk": upload_state["next_chunk"]', SOURCE)
        self.assertIn('"chunk_size": upload_state["chunk_size"]', SOURCE)
        status = load_upload_status_helper("status-session", {
            "next_chunk": 2, "chunk_size": 12 * 1024 * 1024,
            "total_chunks": 4, "received_bytes": 24 * 1024 * 1024,
            "total_size": 48 * 1024 * 1024,
        })
        self.assertEqual(status["chunk_size"], 12 * 1024 * 1024)
        self.assertEqual(status["next_chunk"], 2)
        with self.assertRaises(Exception):
            load_upload_status_helper("invalid-session", {
                "next_chunk": 0, "total_chunks": 2, "total_size": 48 * 1024 * 1024,
            })
        self.assertIn("persist_match_upload_state(upload_id, match_uploads[upload_id])", SOURCE)
        self.assertIn("match_upload_manifest_path(upload_id).unlink(missing_ok=True)", SOURCE)

    def test_frontend_persists_upload_id_and_resumes_from_server_next_chunk(self):
        self.assertIn('async function getPendingMatchUpload()', HTML)
        self.assertIn('async function savePendingMatchUpload(record)', HTML)
        self.assertIn('async function clearPendingMatchUpload()', HTML)
        self.assertIn('saved.sourceKey===identity.sourceKey', HTML)
        self.assertIn("method:'GET',credentials:'omit',cache:'no-store'", HTML)
        self.assertIn('const serverNextChunk=Number(status.next_chunk),serverTotalChunks=Number(status.total_chunks),serverChunkSize=Number(status.chunk_size)', HTML)
        self.assertIn('serverTotalChunks!==Math.ceil(file.size/serverChunkSize)', HTML)
        self.assertIn('chunkSize=serverChunkSize', HTML)
        self.assertIn('nextChunk=serverNextChunk', HTML)
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
        self.assertIn("currentChunkSize=Number(current.chunk_size)", upload)
        self.assertIn("currentChunkSize!==chunkSize", upload)
        self.assertIn("nextChunk=Number(current.next_chunk)", upload)
        self.assertIn("再開情報が送信中に変化しました", upload)

    def test_resume_detects_local_server_checkpoint_mismatch_and_syncs_to_server(self):
        upload = HTML[HTML.index("async function uploadMatchVideoInChunks"):HTML.index("async function fetchMatchJobStatusWithRetry")]
        self.assertIn("const serverNextChunk=Number(status.next_chunk),serverTotalChunks=Number(status.total_chunks),serverChunkSize=Number(status.chunk_size)", upload)
        self.assertIn("chunkSize=serverChunkSize", upload)
        self.assertIn("const localNextChunk=Number(saved.nextChunk),localChunkSize=Number(saved.chunkSize)", upload)
        self.assertIn("chunkSizeMismatch=Number.isInteger(localChunkSize)&&localChunkSize!==serverChunkSize", upload)
        self.assertIn("checkpointMismatch=Number.isInteger(localNextChunk)&&localNextChunk!==serverNextChunk", upload)
        self.assertIn("サーバー側の値を優先します", upload)
        self.assertIn("await persistResume({...identity,uploadId:session.upload_id,chunkSize,totalChunks:total,nextChunk,createdAt:saved.createdAt||Date.now()})", upload)
        self.assertIn("serverNextChunk>serverTotalChunks", upload)

    def test_browser_retry_suite_covers_timeout_and_both_checkpoint_drift_directions(self):
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("def test_timeout_reconciles_chunk_committed_before_response_was_lost", retry_test)
        self.assertIn("def test_retry_stops_when_server_chunk_size_changes_or_is_missing", retry_test)
        self.assertIn("serverNextChunk = 1", retry_test)
        self.assertIn("Network disconnected while checking upload status", retry_test)
        self.assertIn("def test_server_checkpoint_overrides_stale_indexeddb_checkpoint", retry_test)
        self.assertIn("local-behind", retry_test)
        self.assertIn("local-ahead", retry_test)
        self.assertIn("checkpointAtFirstPut", retry_test)
        self.assertIn("timedOut", retry_test)


    def test_browser_resume_suite_covers_page_reload_and_full_browser_restart(self):
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn(
            "def test_indexeddb_resume_survives_page_reload_and_same_video_reselection",
            retry_test
        )
        self.assertIn(
            "def test_indexeddb_resume_survives_browser_process_restart_and_same_video_reselection",
            retry_test
        )
        self.assertIn("launch_persistent_context", retry_test)
        self.assertIn("page.reload(wait_until=\"load\")", retry_test)
        self.assertIn('page.set_input_files("#videoFile"', retry_test)
        self.assertIn("last_modified", retry_test)
        self.assertIn("12 * 1024 * 1024", retry_test)
        self.assertIn("restoredUploadId", retry_test)
        self.assertIn("chunk_size: 12 * 1024 * 1024, total_chunks: 2", retry_test)
        self.assertIn("checkpointChunkSizeAtFirstPut", retry_test)
        self.assertIn("checkpointTotalChunksAtFirstPut", retry_test)
        self.assertIn("self.assertEqual(result[\"restoredChunkSize\"], 6 * 1024 * 1024, result)", retry_test)
        self.assertIn("self.assertEqual(result[\"putIndexes\"], [1], result)")
        self.assertIn("self.assertEqual(result[\"checkpointAtFirstPut\"], 1, result)", retry_test)



    def test_video_fingerprint_progress_cancel_and_memory_boundaries(self):
        self.assertIn("function cancelMatchFingerprint()", HTML)
        self.assertIn("onclick=" + chr(34) + "cancelMatchFingerprint()" + chr(34), HTML)
        self.assertIn("matchFingerprintProgressBar", HTML)
        self.assertIn("progress.completedBytes/progress.totalBytes*100", HTML)
        self.assertIn("error.name='AbortError'", HTML)
        self.assertIn("await new Promise(resolve=>setTimeout(resolve,0))", HTML)
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("test_video_fingerprint_reports_progress_and_cancels_between_12mb_slices", retry_test)

    def test_resume_identity_requires_content_fingerprint_and_hashes_each_12mb_block(self):
        self.assertIn("async function getVideoContentFingerprint(file,chunkSize=12*1024*1024,onProgress", HTML)
        self.assertIn("crypto.subtle.digest('SHA-256',bytes)", HTML)
        self.assertIn("saved.contentFingerprint===identity.contentFingerprint", HTML)
        self.assertIn("!/^[a-f0-9]{64}$/.test(saved.contentFingerprint)", HTML)
        self.assertIn("const contentFingerprint=await getVideoContentFingerprint(file)", HTML)

    def test_resume_rejects_mismatched_or_corrupt_identity_before_reusing_session(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("const savedRecordValid=", html)
        self.assertIn("typeof saved.uploadId==='string'", html)
        self.assertIn("Number.isSafeInteger(saved.size)", html)
        self.assertIn("Number.isInteger(saved.nextChunk)", html)
        self.assertIn("アップロード再開情報の破損または必須項目不足を検出", html)
        self.assertIn("try{await clearPendingMatchUpload()}", html)
        self.assertIn("different_video", retry_test)
        self.assertIn("different_content_same_metadata", retry_test)
        self.assertIn("self.assertEqual(len(results), 13, results)", retry_test)
        self.assertIn("different_size", retry_test)
        self.assertIn("different_last_modified", retry_test)
        self.assertIn("different_mime_type", retry_test)
        self.assertIn("different_jersey_numbers", retry_test)
        self.assertIn("stored_identity_mismatch", retry_test)
        self.assertIn("missing_record", retry_test)
        self.assertIn("corrupt_missing_upload_id", retry_test)
        self.assertIn("corrupt_checkpoint_type", retry_test)
        self.assertIn("corrupt_chunk_size", retry_test)
        self.assertIn("corrupt_nan_checkpoint", retry_test)
        self.assertIn("indexeddb_read_error", retry_test)
        self.assertIn("self.assertEqual(result[\"staleStatusChecks\"], 0, result)", retry_test)
        self.assertIn("12 * 1024 * 1024", retry_test)



    def test_fingerprint_aborts_on_background_and_pagehide_then_allows_restart(self):
        self.assertIn("cancelFingerprintWhenHidden", HTML)
        self.assertIn("document.addEventListener('visibilitychange'", HTML)
        self.assertIn("window.addEventListener('pagehide'", HTML)
        self.assertIn("document.removeEventListener('visibilitychange'", HTML)
        self.assertIn("window.removeEventListener('pagehide'", HTML)
        retry_test = (ROOT / "tests" / "test_match_upload_retry.py").read_text(encoding="utf-8")
        self.assertIn("def test_fingerprint_cancels_on_background_or_pagehide_and_can_restart", retry_test)
        self.assertIn("fetchCallsAfterInterruption", retry_test)
        self.assertIn("restartFetchCalls", retry_test)
        self.assertIn("12*1024*1024", HTML)

if __name__ == "__main__":
    unittest.main()
