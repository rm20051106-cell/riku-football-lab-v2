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

class Stage48ResumableRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.temp.name) / "stage48.webm"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","color=c=blue:s=160x90:d=1:r=12","-an","-c:v","libvpx","-deadline","realtime","-cpu-used","8","-b:v","120k",str(cls.video)],check=True,timeout=30)
        cls.video_bytes = cls.video.read_bytes()
        cls.digest = hashlib.sha256(cls.video_bytes).hexdigest()
        cls.server = ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.playwright=sync_playwright().start()
        self.browser=self.playwright.chromium.launch(headless=True,args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        self.context=self.browser.new_context()
        self.page=self.context.new_page()
        self.page.goto(self.url,wait_until="load")
        self.page.wait_for_function("typeof window.runStage48VideoRestore === 'function'")

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def file(self,key="4801"):
        return {"name":"riku-video__"+key+"__stage48.webm","mimeType":"video/webm","lastModified":1700000000000,"buffer":self.video_bytes}

    def seed(self,ids):
        self.page.evaluate("""ids => { state.clips=ids.map(id=>({id,date:today(),title:"Stage 48 test "+id,hasVideo:false})); persist(); }""",ids)

    def test_sha256_matches_python_and_restore_report_is_persisted(self):
        self.seed([4801])
        self.page.locator("#videoImportFiles").set_input_files(self.file())
        self.page.wait_for_function("document.getElementById('stage48Report')?.textContent.includes('復元完了レポート')",timeout=30000)
        job=self.page.evaluate("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))")
        self.assertEqual(job["items"][0]["hash"],self.digest)
        self.assertEqual(job["items"][0]["savedHash"],self.digest)
        self.assertEqual(job["items"][0]["status"],"done")
        self.assertIn("完了動画",self.page.locator("#stage48Report").inner_text())
        self.assertIn("復元",self.page.locator("#stage48History").inner_text())

    def test_interrupted_restore_resumes_from_saved_checkpoint(self):
        self.seed([4803])
        encoded=base64.b64encode(self.video_bytes).decode("ascii")
        paused_status=self.page.evaluate("""async data => { const raw=atob(data); const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)); const file=new File([bytes],"riku-video__4803__stage48.webm",{type:"video/webm",lastModified:1700000000000}); setTimeout(()=>window.pauseStage48Restore(),0); await window.runStage48VideoRestore([file]); return JSON.parse(localStorage.getItem("rikuVideoRestoreJob_v1")).items[0].status; }""",encoded)
        self.assertEqual(paused_status,"pending")
        resumed=self.page.evaluate("""async data => { const raw=atob(data); const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)); const file=new File([bytes],"riku-video__4803__stage48.webm",{type:"video/webm",lastModified:1700000000000}); await window.runStage48VideoRestore([file]); return JSON.parse(localStorage.getItem("rikuVideoRestoreJob_v1")).items[0]; }""",encoded)
        self.assertEqual(resumed["status"],"done")
        self.assertEqual(resumed["savedHash"],self.digest)

    def test_webkit_streaming_sha256_is_compatible(self):
        browser=self.playwright.webkit.launch(headless=True)
        page=browser.new_page()
        page.goto(self.url,wait_until="load")
        digest=page.evaluate("""async () => { const data=new TextEncoder().encode("RIKU FOOTBALL LAB Stage 48 SHA-256"); return window.hashStage48Blob(new Blob([data])); }""")
        self.assertEqual(digest,hashlib.sha256(b"RIKU FOOTBALL LAB Stage 48 SHA-256").hexdigest())
        browser.close()

    def test_failed_video_only_retry_completes(self):
        self.seed([4802])
        self.page.evaluate("""() => { const original=window.storeClipVideo; window.__originalStore=original; window.storeClipVideo=async (...args)=>{window.storeClipVideo=window.__originalStore;throw new Error("simulated temporary write failure")}; }""")
        self.page.locator("#videoImportFiles").set_input_files(self.file("4802"))
        self.page.wait_for_function("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))?.items?.[0]?.status === 'failed'",timeout=30000)
        self.page.wait_for_function("document.getElementById('stage48Status')?.textContent.includes('失敗動画だけ再試行できます')",timeout=30000)
        self.page.evaluate("document.getElementById('stage48Retry').click()")
        self.page.locator("#videoImportFiles").set_input_files(self.file("4802"))
        self.page.wait_for_function("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1'))?.items?.[0]?.status === 'done'",timeout=30000)
        self.assertEqual(self.page.evaluate("JSON.parse(localStorage.getItem('rikuVideoRestoreJob_v1')).items[0].savedHash"),self.digest)

if __name__ == "__main__":
    unittest.main()
