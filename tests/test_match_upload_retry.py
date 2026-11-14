import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class MatchUploadRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_chunk_and_completion_lost_responses_are_retried_idempotently(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox"]
            )
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(self.url, wait_until="load")
                page.wait_for_function(
                    "typeof uploadMatchVideoInChunks === 'function'"
                )
                result = page.evaluate("""async () => {
                    state.settings.apiBaseUrl = 'https://upload-retry.test';
                    let chunkAttempts = 0;
                    let chunkSizes = [];
                    let completeAttempts = 0;
                    let serverJobId = null;
                    let deleteAttempts = 0;
                    window.fetch = async (url, options = {}) => {
                        const path = new URL(url).pathname;
                        if (path === '/analyze/match/uploads' && options.method === 'POST') {
                            return new Response(JSON.stringify({
                                ok: true, upload_id: 'retry-session',
                                chunk_size: 12 * 1024 * 1024, total_chunks: 2
                            }), {status: 201, headers: {'Content-Type': 'application/json'}});
                        }
                        if (path === '/analyze/match/uploads/retry-session' && options.method === 'GET') {
                            return new Response(JSON.stringify({
                                upload_id: 'retry-session', total_bytes: 12 * 1024 * 1024 + 1,
                                received_bytes: 0, next_chunk: 0, total_chunks: 2
                            }), {status: 200, headers: {'Content-Type': 'application/json'}});
                        }
                        if ((path === '/analyze/match/uploads/retry-session/0' || path === '/analyze/match/uploads/retry-session/1') && options.method === 'PUT') {
                            chunkAttempts++;
                            chunkSizes.push(options.body.get('file').size);
                            if (path.endsWith('/0') && chunkSizes.filter(size => size === 12 * 1024 * 1024).length === 1) {
                                throw new TypeError('Load failed');
                            }
                            return new Response(JSON.stringify({ok: true}), {
                                status: 200, headers: {'Content-Type': 'application/json'}
                            });
                        }
                        if (path === '/analyze/match/uploads/retry-session/complete' && options.method === 'POST') {
                            completeAttempts++;
                            if (completeAttempts === 1) {
                                serverJobId = 'retry-job';
                                throw new TypeError('Load failed');
                            }
                            return new Response(JSON.stringify({
                                ok: true, job_id: serverJobId || 'retry-job', status: 'queued'
                            }), {status: 202, headers: {'Content-Type': 'application/json'}});
                        }
                        if (path === '/analyze/match/uploads/retry-session' && options.method === 'DELETE') {
                            deleteAttempts++;
                            return new Response(JSON.stringify({ok: true}), {status: 200});
                        }
                        throw new Error('Unexpected request: ' + options.method + ' ' + path);
                    };
                    const video = document.getElementById('matchVideo');
                    Object.defineProperty(video, 'duration', {configurable: true, value: 60});
                    const file = new File([new Uint8Array(12 * 1024 * 1024 + 1)], 'retry.mp4', {
                        type: 'video/mp4'
                    });
                    const status = document.createElement('div');
                    const response = await uploadMatchVideoInChunks(file, ['10', '74'], status);
                    return {chunkAttempts, chunkSizes, completeAttempts, deleteAttempts, response};
                }""")
                self.assertEqual(result["chunkAttempts"], 3, result)
                self.assertEqual(result["chunkSizes"], [12 * 1024 * 1024, 12 * 1024 * 1024, 1], result)
                self.assertEqual(result["completeAttempts"], 2, result)
                self.assertEqual(result["deleteAttempts"], 0, result)
                self.assertEqual(result["response"]["job_id"], "retry-job", result)
            finally:
                browser.close()


    def test_timeout_aborts_chunk_and_retries_after_server_reconciliation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox"]
            )
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(self.url, wait_until="load")
                page.wait_for_function(
                    "typeof uploadMatchVideoInChunks === 'function'"
                )
                result = page.evaluate("""async () => {
                    state.settings.apiBaseUrl = 'https://upload-timeout.test';
                    const originalSetTimeout = window.setTimeout.bind(window);
                    window.setTimeout = (callback, delay, ...args) =>
                        originalSetTimeout(callback, delay === 120000 ? 0 : delay, ...args);
                    let putAttempts = 0;
                    let timedOut = false;
                    let statusChecks = 0;
                    window.fetch = async (url, options = {}) => {
                        const path = new URL(url).pathname;
                        if (path === '/analyze/match/uploads' && options.method === 'POST') {
                            return new Response(JSON.stringify({
                                upload_id: 'timeout-session',
                                chunk_size: 12 * 1024 * 1024,
                                total_chunks: 1
                            }), {status: 201, headers: {'Content-Type': 'application/json'}});
                        }
                        if (path === '/analyze/match/uploads/timeout-session' && options.method === 'GET') {
                            statusChecks++;
                            return new Response(JSON.stringify({
                                upload_id: 'timeout-session',
                                total_bytes: 12 * 1024 * 1024,
                                next_chunk: 0,
                                total_chunks: 1
                            }), {status: 200, headers: {'Content-Type': 'application/json'}});
                        }
                        if (path === '/analyze/match/uploads/timeout-session/0' && options.method === 'PUT') {
                            putAttempts++;
                            if (putAttempts === 1) {
                                return new Promise((resolve, reject) => {
                                    if (options.signal.aborted) {
                                        timedOut = true;
                                        reject(new DOMException('Aborted', 'AbortError'));
                                        return;
                                    }
                                    options.signal.addEventListener('abort', () => {
                                        timedOut = true;
                                        reject(new DOMException('Aborted', 'AbortError'));
                                    }, {once: true});
                                });
                            }
                            return new Response(JSON.stringify({ok: true}), {status: 200});
                        }
                        if (path === '/analyze/match/uploads/timeout-session/complete' && options.method === 'POST') {
                            return new Response(JSON.stringify({
                                job_id: 'timeout-job', status: 'queued'
                            }), {status: 202, headers: {'Content-Type': 'application/json'}});
                        }
                        throw new Error('Unexpected request: ' + options.method + ' ' + path);
                    };
                    const video = document.getElementById('matchVideo');
                    Object.defineProperty(video, 'duration', {configurable: true, value: 60});
                    const file = new File([new Uint8Array(12 * 1024 * 1024)], 'timeout.mp4', {
                        type: 'video/mp4'
                    });
                    const response = await uploadMatchVideoInChunks(file, ['10', '74'], document.createElement('div'));
                    return {putAttempts, timedOut, statusChecks, jobId: response.job_id};
                }""")
                self.assertEqual(result["putAttempts"], 2, result)
                self.assertTrue(result["timedOut"], result)
                self.assertEqual(result["statusChecks"], 1, result)
                self.assertEqual(result["jobId"], "timeout-job", result)
            finally:
                browser.close()

    def test_server_checkpoint_overrides_stale_indexeddb_checkpoint(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox"]
            )
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(self.url, wait_until="load")
                page.wait_for_function(
                    "typeof uploadMatchVideoInChunks === 'function' && typeof savePendingMatchUpload === 'function'"
                )
                results = page.evaluate("""async () => {
                    state.settings.apiBaseUrl = 'https://upload-reconcile.test';
                    const video = document.getElementById('matchVideo');
                    Object.defineProperty(video, 'duration', {configurable: true, value: 60});
                    const file = new File([new Uint8Array(12 * 1024 * 1024 + 1)], 'reconcile.mp4', {
                        type: 'video/mp4', lastModified: 12345
                    });
                    const sourceKey = getVideoSourceKey(file);
                    const cases = [
                        {id: 'local-behind', localNext: 0, serverNext: 1},
                        {id: 'local-ahead', localNext: 2, serverNext: 0}
                    ];
                    const observed = [];
                    for (const item of cases) {
                        const uploadId = 'reconcile-' + item.id;
                        await savePendingMatchUpload({
                            sourceKey, size: file.size, name: file.name,
                            lastModified: file.lastModified, jerseyNumbers: ['10', '74'],
                            uploadId, chunkSize: 12 * 1024 * 1024,
                            totalChunks: 2, nextChunk: item.localNext, createdAt: 1
                        });
                        const putIndexes = [];
                        let checkpointAtFirstPut = null;
                        window.fetch = async (url, options = {}) => {
                            const path = new URL(url).pathname;
                            if (path === '/analyze/match/uploads/' + uploadId && options.method === 'GET') {
                                return new Response(JSON.stringify({
                                    upload_id: uploadId, total_bytes: file.size,
                                    next_chunk: item.serverNext, total_chunks: 2
                                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                            }
                            if (path.startsWith('/analyze/match/uploads/' + uploadId + '/') &&
                                options.method === 'PUT' && !path.endsWith('/complete')) {
                                const index = Number(path.split('/').pop());
                                putIndexes.push(index);
                                if (checkpointAtFirstPut === null) {
                                    const saved = await getPendingMatchUpload();
                                    checkpointAtFirstPut = saved?.nextChunk ?? null;
                                }
                                return new Response(JSON.stringify({ok: true}), {status: 200});
                            }
                            if (path === '/analyze/match/uploads/' + uploadId + '/complete' &&
                                options.method === 'POST') {
                                return new Response(JSON.stringify({
                                    job_id: 'job-' + item.id, status: 'queued'
                                }), {status: 202, headers: {'Content-Type': 'application/json'}});
                            }
                            throw new Error('Unexpected request: ' + options.method + ' ' + path);
                        };
                        await uploadMatchVideoInChunks(file, ['10', '74'], document.createElement('div'));
                        observed.push({
                            id: item.id, localNext: item.localNext,
                            serverNext: item.serverNext, putIndexes, checkpointAtFirstPut
                        });
                    }
                    return observed;
                }""")
                self.assertEqual(results[0]["putIndexes"], [1], results)
                self.assertEqual(results[0]["checkpointAtFirstPut"], 1, results)
                self.assertEqual(results[1]["putIndexes"], [0, 1], results)
                self.assertEqual(results[1]["checkpointAtFirstPut"], 0, results)
            finally:
                browser.close()


    def _verify_resume_after_storage_survives_restart(self, restart_browser):
        import tempfile

        with sync_playwright() as playwright:
            with tempfile.TemporaryDirectory() as user_data_dir:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir, headless=True, args=["--no-sandbox"],
                    viewport={"width": 390, "height": 844}
                )
                try:
                    page = context.new_page()
                    page.goto(self.url, wait_until="load")
                    page.wait_for_function(
                        "typeof uploadMatchVideoInChunks === 'function' && typeof savePendingMatchUpload === 'function'"
                    )
                    seeded = page.evaluate("""async () => {
                        state.settings.apiBaseUrl = 'https://resume-restart.test';
                        persist();
                        const file = new File(
                            [new Uint8Array(12 * 1024 * 1024 + 1)],
                            'restart-resume.mp4',
                            {type: 'video/mp4', lastModified: 12345}
                        );
                        const sourceKey = getVideoSourceKey(file);
                        await savePendingMatchUpload({
                            sourceKey, size: file.size, name: file.name,
                            lastModified: file.lastModified, jerseyNumbers: '10,74',
                            uploadId: 'restart-session', chunkSize: 12 * 1024 * 1024,
                            totalChunks: 2, nextChunk: 0, createdAt: 123
                        });
                        return {sourceKey, size: file.size, lastModified: file.lastModified};
                    }""")

                    if restart_browser:
                        context.close()
                        context = playwright.chromium.launch_persistent_context(
                            user_data_dir, headless=True, args=["--no-sandbox"],
                            viewport={"width": 390, "height": 844}
                        )
                        page = context.new_page()
                        page.goto(self.url, wait_until="load")
                    else:
                        page.reload(wait_until="load")

                    page.wait_for_function(
                        "typeof uploadMatchVideoInChunks === 'function' && typeof getPendingMatchUpload === 'function'"
                    )
                    page.set_input_files("#videoFile", {
                        "name": "restart-resume.mp4",
                        "mimeType": "video/mp4",
                        "buffer": b"\x00" * (12 * 1024 * 1024 + 1),
                        "last_modified": 12345
                    })
                    result = page.evaluate("""async () => {
                        await pendingMatchSave;
                        const file = document.getElementById('videoFile').files[0];
                        const restored = await getPendingMatchUpload();
                        const sourceKey = getVideoSourceKey(file);
                        const putIndexes = [];
                        const putSizes = [];
                        let checkpointAtFirstPut = null;
                        let statusChecks = 0;
                        window.fetch = async (url, options = {}) => {
                            const path = new URL(url).pathname;
                            if (path === '/analyze/match/uploads/restart-session' &&
                                options.method === 'GET') {
                                statusChecks++;
                                return new Response(JSON.stringify({
                                    upload_id: 'restart-session',
                                    total_bytes: file.size,
                                    received_bytes: 12 * 1024 * 1024,
                                    next_chunk: 1, total_chunks: 2
                                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                            }
                            if (path === '/analyze/match/uploads/restart-session/1' &&
                                options.method === 'PUT') {
                                putIndexes.push(1);
                                putSizes.push(options.body.get('file').size);
                                checkpointAtFirstPut = (await getPendingMatchUpload())?.nextChunk ?? null;
                                return new Response(JSON.stringify({ok: true}), {
                                    status: 200, headers: {'Content-Type': 'application/json'}
                                });
                            }
                            if (path === '/analyze/match/uploads/restart-session/complete' &&
                                options.method === 'POST') {
                                return new Response(JSON.stringify({
                                    job_id: 'restart-resume-job', status: 'queued'
                                }), {status: 202, headers: {'Content-Type': 'application/json'}});
                            }
                            throw new Error('Unexpected request: ' + options.method + ' ' + path);
                        };
                        const response = await uploadMatchVideoInChunks(
                            file, '10,74', document.createElement('div')
                        );
                        return {
                            restoredUploadId: restored?.uploadId || null,
                            restoredNextChunk: restored?.nextChunk ?? null,
                            restoredChunkSize: restored?.chunkSize ?? null,
                            selectedSourceKey: sourceKey,
                            selectedSize: file.size,
                            selectedLastModified: file.lastModified,
                            putIndexes, putSizes, checkpointAtFirstPut, statusChecks,
                            jobId: response.job_id
                        };
                    }""")
                    self.assertEqual(result["restoredUploadId"], "restart-session", result)
                    self.assertEqual(result["restoredNextChunk"], 0, result)
                    self.assertEqual(result["restoredChunkSize"], 12 * 1024 * 1024, result)
                    self.assertEqual(result["selectedSourceKey"], seeded["sourceKey"], result)
                    self.assertEqual(result["selectedSize"], seeded["size"], result)
                    self.assertEqual(result["selectedLastModified"], seeded["lastModified"], result)
                    self.assertEqual(result["statusChecks"], 1, result)
                    self.assertEqual(result["putIndexes"], [1], result)
                    self.assertEqual(result["putSizes"], [1], result)
                    self.assertEqual(result["checkpointAtFirstPut"], 1, result)
                    self.assertEqual(result["jobId"], "restart-resume-job", result)
                finally:
                    context.close()

    def test_indexeddb_resume_survives_page_reload_and_same_video_reselection(self):
        self._verify_resume_after_storage_survives_restart(restart_browser=False)

    def test_indexeddb_resume_survives_browser_process_restart_and_same_video_reselection(self):
        self._verify_resume_after_storage_survives_restart(restart_browser=True)


    def test_mismatched_video_identity_and_invalid_resume_records_start_fresh_sessions(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.goto(self.url, wait_until="load")
                page.wait_for_function(
                    "typeof uploadMatchVideoInChunks === 'function' && typeof savePendingMatchUpload === 'function'"
                )
                results = page.evaluate("""async () => {
                    state.settings.apiBaseUrl = 'https://safe-resume.test';
                    const CHUNK = 12 * 1024 * 1024;
                    const cases = [
                        'different_video', 'different_size', 'different_last_modified',
                        'different_mime_type', 'stored_identity_mismatch',
                        'missing_record', 'corrupt_missing_upload_id',
                        'corrupt_checkpoint_type', 'corrupt_chunk_size', 'corrupt_nan_checkpoint', 'indexeddb_read_error'
                    ];
                    const outcomes = [];
                    const nativeGetPending = window.getPendingMatchUpload;
                    for (const caseName of cases) {
                        const original = new File(
                            [new Uint8Array(CHUNK + 1)], 'match.mp4',
                            {type: 'video/mp4', lastModified: 111}
                        );
                        let selected = original;
                        if (caseName === 'different_video') {
                            selected = new File([new Uint8Array(CHUNK + 1)], 'other-match.mp4',
                                {type: 'video/mp4', lastModified: 111});
                        } else if (caseName === 'different_size') {
                            selected = new File([new Uint8Array(CHUNK + 2)], 'match.mp4',
                                {type: 'video/mp4', lastModified: 111});
                        } else if (caseName === 'different_last_modified') {
                            selected = new File([new Uint8Array(CHUNK + 1)], 'match.mp4',
                                {type: 'video/mp4', lastModified: 222});
                        } else if (caseName === 'different_mime_type') {
                            selected = new File([new Uint8Array(CHUNK + 1)], 'match.mp4',
                                {type: 'video/quicktime', lastModified: 111});
                        }
                        await clearPendingMatchUpload();
                        const originalKey = getVideoSourceKey(original);
                        const stale = {
                            sourceKey: originalKey, size: original.size, name: original.name,
                            lastModified: original.lastModified, jerseyNumbers: '10,74',
                            uploadId: 'stale-' + caseName, chunkSize: CHUNK,
                            totalChunks: 2, nextChunk: 1, createdAt: 123
                        };
                        if (caseName === 'stored_identity_mismatch') stale.sourceKey = 'tampered-source-key';
                        if (caseName === 'corrupt_missing_upload_id') delete stale.uploadId;
                        if (caseName === 'corrupt_checkpoint_type') stale.nextChunk = '1';
                        if (caseName === 'corrupt_nan_checkpoint') stale.nextChunk = NaN;
                        if (caseName === 'corrupt_chunk_size') stale.chunkSize = -1;
                        if (caseName !== 'missing_record' && caseName !== 'indexeddb_read_error') {
                            await savePendingMatchUpload(stale);
                        }
                        if (caseName === 'indexeddb_read_error') {
                            window.getPendingMatchUpload = async () => {
                                throw new Error('simulated IndexedDB read failure');
                            };
                        } else {
                            window.getPendingMatchUpload = nativeGetPending;
                        }

                        let createCount = 0, staleStatusChecks = 0, freshStatusChecks = 0;
                        const putIndexes = [], putSizes = [];
                        const freshId = 'fresh-' + caseName;
                        window.fetch = async (url, options = {}) => {
                            const path = new URL(url).pathname;
                            if (path === '/analyze/match/uploads' && options.method === 'POST') {
                                createCount++;
                                return new Response(JSON.stringify({
                                    ok: true, upload_id: freshId,
                                    chunk_size: CHUNK, total_chunks: 2
                                }), {status: 201, headers: {'Content-Type': 'application/json'}});
                            }
                            if (path.startsWith('/analyze/match/uploads/stale-') &&
                                options.method === 'GET') {
                                staleStatusChecks++;
                                return new Response(JSON.stringify({
                                    upload_id: 'unexpected-stale-session',
                                    total_bytes: original.size, next_chunk: 1, total_chunks: 2
                                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                            }
                            if (path === '/analyze/match/uploads/' + freshId &&
                                options.method === 'GET') {
                                freshStatusChecks++;
                                return new Response(JSON.stringify({
                                    upload_id: freshId, total_bytes: selected.size,
                                    received_bytes: 0, next_chunk: 0, total_chunks: 2
                                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                            }
                            if ((path === '/analyze/match/uploads/' + freshId + '/0' ||
                                 path === '/analyze/match/uploads/' + freshId + '/1') &&
                                options.method === 'PUT') {
                                const index = Number(path.split('/').pop());
                                putIndexes.push(index);
                                putSizes.push(options.body.get('file').size);
                                return new Response(JSON.stringify({ok: true}), {
                                    status: 200, headers: {'Content-Type': 'application/json'}
                                });
                            }
                            if (path === '/analyze/match/uploads/' + freshId + '/complete' &&
                                options.method === 'POST') {
                                return new Response(JSON.stringify({
                                    ok: true, job_id: 'job-' + caseName, status: 'queued'
                                }), {status: 202, headers: {'Content-Type': 'application/json'}});
                            }
                            throw new Error('Unexpected request: ' + options.method + ' ' + path);
                        };
                        const response = await uploadMatchVideoInChunks(
                            selected, '10,74', document.createElement('div')
                        );
                        outcomes.push({
                            caseName, createCount, staleStatusChecks, freshStatusChecks,
                            putIndexes, putSizes, expectedSize: selected.size,
                            jobId: response.job_id
                        });
                        window.getPendingMatchUpload = nativeGetPending;
                    }
                    return outcomes;
                }""")
                self.assertEqual(len(results), 11, results)
                for result in results:
                    with self.subTest(case=result["caseName"]):
                        self.assertEqual(result["createCount"], 1, result)
                        self.assertEqual(result["staleStatusChecks"], 0, result)
                        self.assertEqual(result["freshStatusChecks"], 0, result)
                        self.assertEqual(result["putIndexes"], [0, 1], result)
                        self.assertEqual(result["putSizes"][0], 12 * 1024 * 1024, result)
                        self.assertEqual(sum(result["putSizes"]), result["expectedSize"], result)
                        self.assertTrue(result["jobId"].startswith("job-"), result)
            finally:
                browser.close()



if __name__ == "__main__":
    unittest.main(verbosity=2)
