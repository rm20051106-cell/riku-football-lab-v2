import base64
import hashlib
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class Stage54RestoreCheckpointIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.temp.name) / "stage54.webm"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=orange:s=160x90:d=1:r=12",
            "-an", "-c:v", "libvpx", "-deadline", "realtime",
            "-cpu-used", "8", "-b:v", "120k", str(cls.video)
        ], check=True, timeout=30)
        cls.video_bytes = cls.video.read_bytes()
        cls.digest = hashlib.sha256(cls.video_bytes).hexdigest()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(SimpleHTTPRequestHandler, directory=str(ROOT))
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"]
        )
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(self.url, wait_until="load")
        self.page.wait_for_function("typeof window.runStage48VideoRestore === 'function'")

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def seed(self, record_id):
        self.page.evaluate("""id => {
            state.clips = [{id, date: today(), title: "Stage 54 checkpoint test", hasVideo: false}];
            persist();
        }""", record_id)

    def run_backup(self, record_id, data=None):
        raw = base64.b64encode(data if data is not None else self.video_bytes).decode("ascii")
        self.page.evaluate("""async args => {
            const raw = atob(args.data);
            const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
            const file = new File([bytes], "riku-video__" + args.id + "__stage54.webm",
                {type: "video/webm", lastModified: 1700000000000});
            await window.runStage48VideoRestore([file]);
        }""", {"id": str(record_id), "data": raw})

    def wait_done(self):
        self.page.wait_for_function(
            "JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))?.items?.[0]?.status === 'done'",
            timeout=30000
        )

    def test_deleted_completed_video_is_recovered_from_backup(self):
        self.seed(5401)
        self.run_backup(5401)
        self.wait_done()
        self.page.evaluate("() => removeClipVideo('5401')")
        self.run_backup(5401)
        self.wait_done()
        result = self.page.evaluate("""async () => {
            const row = await getClipVideo("5401");
            return {size: row?.blob?.size, hash: await window.hashStage48Blob(row.blob)};
        }""")
        self.assertEqual(result["size"], len(self.video_bytes))
        self.assertEqual(result["hash"], self.digest)
        self.assertEqual(
            self.page.evaluate("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1')).items[0].savedHash"),
            self.digest
        )

    def test_different_existing_video_is_blocked_without_overwrite(self):
        self.seed(5402)
        self.run_backup(5402)
        self.wait_done()
        tampered = bytes([self.video_bytes[0] ^ 1]) + self.video_bytes[1:]
        tampered_b64 = base64.b64encode(tampered).decode("ascii")
        self.page.evaluate("""async encoded => {
            const raw = atob(encoded);
            const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
            await storeClipVideo("5402", new File([bytes], "existing.webm", {type:"video/webm"}));
        }""", tampered_b64)
        self.run_backup(5402)
        job = self.page.evaluate("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))")
        self.assertEqual(job["items"][0]["status"], "blocked")
        self.assertIn("別内容動画", job["items"][0]["error"])
        stored_hash = self.page.evaluate("""async () => {
            const row = await getClipVideo("5402");
            return window.hashStage48Blob(row.blob);
        }""")
        self.assertEqual(stored_hash, hashlib.sha256(tampered).hexdigest())
        self.assertNotEqual(stored_hash, self.digest)
        self.assertIn("安全停止", self.page.locator("#stage48Report").inner_text())

    def test_changed_source_with_same_name_and_size_is_blocked(self):
        self.seed(5403)
        self.run_backup(5403)
        self.wait_done()
        tampered = bytes([self.video_bytes[0] ^ 1]) + self.video_bytes[1:]
        self.run_backup(5403, tampered)
        job = self.page.evaluate("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))")
        self.assertEqual(job["items"][0]["status"], "blocked")
        self.assertIn("選択動画のSHA-256が異なります", job["items"][0]["error"])
        stored_hash = self.page.evaluate("""async () => {
            const row = await getClipVideo("5403");
            return window.hashStage48Blob(row.blob);
        }""")
        self.assertEqual(stored_hash, self.digest)


if __name__ == "__main__":
    unittest.main()
