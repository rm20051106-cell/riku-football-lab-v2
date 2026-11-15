import base64
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class Stage47VideoRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.temp.name) / "stage47.webm"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=lime:s=160x90:d=1:r=12",
            "-an", "-c:v", "libvpx", "-deadline", "realtime",
            "-cpu-used", "8", "-b:v", "120k", str(cls.video)
        ], check=True, timeout=30)
        cls.video_bytes = cls.video.read_bytes()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
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
        self.browser = self.playwright.chromium.launch(headless=True, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        self.page.goto(self.url, wait_until="load")
        self.page.wait_for_function("typeof window.runStage47VideoRestore === 'function'")
        self.page.evaluate("window.__stage48Intercept = false")
        self.page.on("dialog", lambda dialog: dialog.accept())

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def named_file(self, key, name="stage47.webm"):
        return {
            "name": "riku-video__" + key + "__" + name,
            "mimeType": "video/webm",
            "buffer": self.video_bytes,
        }

    def test_restore_preflight_preview_and_real_playback(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{id: 4701, title: 'Stage 47 test kick', hasVideo: false}];
            persist();
            window.__lastVideoImportAlert = '';
            window.alert = message => { window.__lastVideoImportAlert = String(message); };
        }""")
        page.locator("#videoImportFiles").set_input_files(self.named_file("4701"))
        page.wait_for_function("window.__lastVideoImportAlert.includes('バイト照合')")
        preview = page.locator("#videoRestorePreview").inner_text()
        self.assertIn("復元前プレビュー", preview)
        self.assertIn("事前確認：成功", preview)
        self.assertIn("バイト照合", page.evaluate("window.__lastVideoImportAlert"))
        saved = page.evaluate("async () => { const row = await getClipVideo('4701'); return {size: row.blob.size, type: row.blob.type}; }")
        self.assertEqual(saved["size"], len(self.video_bytes))
        page.evaluate("playSavedClip(4701, 0)")
        page.wait_for_function("document.getElementById('matchVideo').readyState >= 2", timeout=10000)
        page.evaluate("document.getElementById('matchVideo').play()")
        page.wait_for_function("document.getElementById('matchVideo').ended", timeout=10000)

    def test_failed_batch_rolls_back_previously_written_video_and_flags(self):
        page = self.page
        old = base64.b64encode(b"original-video-sentinel").decode("ascii")
        page.evaluate("""old => {
            state.clips = [
                {id: 4702, date: today(), title: 'Existing', hasVideo: true},
                {id: 4703, date: today(), title: 'New', hasVideo: false}
            ];
            persist();
            const bytes = Uint8Array.from(atob(old), c => c.charCodeAt(0));
            return storeClipVideo('4702', new File([bytes], 'old.bin', {type:'application/octet-stream'}));
        }""", old)
        page.evaluate("""() => {
            window.__lastVideoImportAlert = '';
            window.alert = message => { window.__lastVideoImportAlert = String(message); };
            const original = window.storeClipVideo;
            let calls = 0;
            window.storeClipVideo = async (...args) => {
                calls++;
                if (calls === 2) throw new Error('simulated second write failure');
                return original(...args);
            };
        }""")
        page.locator("#videoImportFiles").set_input_files([self.named_file("4702"), self.named_file("4703")])
        page.wait_for_function("window.__lastVideoImportAlert.includes('ロールバック')")
        result = page.evaluate("""async () => ({
            first: await (async()=>{const x=await getClipVideo('4702');return [...new Uint8Array(await x.blob.arrayBuffer())]})(),
            second: await getClipVideo('4703'),
            flags: state.clips.map(x=>x.hasVideo)
        })""")
        self.assertEqual(bytes(result["first"]), b"original-video-sentinel")
        self.assertIsNone(result["second"])
        self.assertEqual(result["flags"], [True, False])

    def test_integrity_scan_flags_nonempty_but_undecodable_video(self):
        page = self.page
        page.evaluate("""async () => {
            await storeClipVideo('orphan-corrupt', new Blob([new Uint8Array([1, 2, 3, 4, 5])], {type:'video/webm'}));
            await scanSavedVideoIntegrity();
        }""")
        page.wait_for_function("document.getElementById('videoIntegrityResult').textContent.includes('読み取り不可 1本')")
        report = page.locator("#videoIntegrityResult").inner_text()
        self.assertIn("Stage 47 再生情報検査", report)
        self.assertIn("orphan-corrupt", report)

    def test_unknown_record_is_rejected_before_any_database_write(self):
        page = self.page
        page.evaluate("() => { state.clips=[]; state.forms=[]; persist(); window.__lastVideoImportAlert=''; window.alert=m=>window.__lastVideoImportAlert=String(m); }")
        page.locator("#videoImportFiles").set_input_files(self.named_file("does-not-exist"))
        page.wait_for_function("window.__lastVideoImportAlert.includes('事前検査')")
        self.assertIn("現在の動画・分析記録は変更していません", page.locator("#videoRestorePreview").inner_text())
        self.assertIsNone(page.evaluate("getClipVideo('does-not-exist')"))


    def test_stage48_keeps_successful_video_and_retries_only_failed_video(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [
                {id: 4811, date: today(), title: 'First retry', hasVideo: false},
                {id: 4812, date: today(), title: 'Successful sibling', hasVideo: false}
            ];
            persist();
            window.__stage48Intercept = true;
            window.__stage48Calls = [];
            window.__stage48FailFirst = true;
            window.runStage47VideoRestore = async files => {
                const file = files[0];
                window.__stage48Calls.push(file.name);
                const match = file.name.match(/^riku-video__(.+?)__(.+)$/);
                if (!match) throw new Error('bad test filename');
                const key = decodeURIComponent(match[1]);
                if (key === '4811' && window.__stage48FailFirst) {
                    window.__stage48FailFirst = false;
                    throw new Error('simulated one-video write failure');
                }
                await storeClipVideo(key, file);
                const record = state.clips.find(row => String(row.id) === key);
                record.hasVideo = true;
                if (!persist()) throw new Error('simulated state persistence failure');
                return {ok: true};
            };
        }""")
        result = page.evaluate("""async () => {
            const bytes = new Uint8Array([9, 8, 7, 6, 5]);
            const files = [
                new File([bytes], 'riku-video__4811__failed.webm', {type:'video/webm', lastModified:1000}),
                new File([bytes], 'riku-video__4812__success.webm', {type:'video/webm', lastModified:1000})
            ];
            await runStage48VideoRestore(files);
            const first = JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'));
            const successfulBeforeRetry = await getClipVideo('4812');
            const failedBeforeRetry = await getClipVideo('4811');
            const firstCalls = [...window.__stage48Calls];
            await retryStage48FailedVideos(files);
            const second = JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'));
            const successfulAfterRetry = await getClipVideo('4812');
            return {
                firstStatuses: first.items.map(x => x.status),
                secondStatuses: second.items.map(x => x.status),
                firstCalls,
                allCalls: window.__stage48Calls,
                successfulBeforeRetry: successfulBeforeRetry?.blob?.size || 0,
                failedBeforeRetry: !!failedBeforeRetry,
                successfulAfterRetry: successfulAfterRetry?.blob?.size || 0,
                flags: state.clips.map(x => x.hasVideo)
            };
        }""")
        self.assertEqual(result["firstStatuses"], ["failed", "done"], result)
        self.assertEqual(result["secondStatuses"], ["done", "done"], result)
        self.assertEqual(len(result["firstCalls"]), 2, result)
        self.assertEqual(result["allCalls"][-1:], ["riku-video__4811__failed.webm"], result)
        self.assertEqual(result["successfulBeforeRetry"], 5, result)
        self.assertFalse(result["failedBeforeRetry"], result)
        self.assertEqual(result["successfulAfterRetry"], 5, result)
        self.assertEqual(result["flags"], [True, True], result)


if __name__ == "__main__":
    unittest.main()
