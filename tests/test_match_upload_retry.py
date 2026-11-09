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
                    let completeAttempts = 0;
                    let serverJobId = null;
                    let deleteAttempts = 0;
                    window.fetch = async (url, options = {}) => {
                        const path = new URL(url).pathname;
                        if (path === '/analyze/match/uploads' && options.method === 'POST') {
                            return new Response(JSON.stringify({
                                ok: true, upload_id: 'retry-session',
                                chunk_size: 6 * 1024 * 1024, total_chunks: 1
                            }), {status: 201, headers: {'Content-Type': 'application/json'}});
                        }
                        if (path === '/analyze/match/uploads/retry-session/0' && options.method === 'PUT') {
                            chunkAttempts++;
                            if (chunkAttempts === 1) throw new TypeError('Load failed');
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
                    const file = new File([new Uint8Array(1024 * 1024)], 'retry.mp4', {
                        type: 'video/mp4'
                    });
                    const status = document.createElement('div');
                    const response = await uploadMatchVideoInChunks(file, ['10', '74'], status);
                    return {chunkAttempts, completeAttempts, deleteAttempts, response};
                }""")
                self.assertEqual(result["chunkAttempts"], 2, result)
                self.assertEqual(result["completeAttempts"], 2, result)
                self.assertEqual(result["deleteAttempts"], 0, result)
                self.assertEqual(result["response"]["job_id"], "retry-job", result)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
