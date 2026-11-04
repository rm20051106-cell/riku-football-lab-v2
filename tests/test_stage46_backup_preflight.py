import hashlib
import json
import unittest
from pathlib import Path
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class Stage46BackupPreflightTests(unittest.TestCase):
    # Browser-level checks ensure the preflight remains strictly read-only.
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        self.page.goto(self.url, wait_until="load")
        self.page.wait_for_function("typeof inspectBackupFile === 'function'")

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def backup_file(self, tamper=False):
        state = {
            "settings": {"name": "Riku"},
            "trainings": [{"id": 1, "menu": "touch"}],
            "measures": [{"id": 2, "value": 5.07}],
            "clips": [{"id": 3, "hasVideo": True}],
            "forms": [],
            "matchAnalyses": [],
            "aiFormAnalyses": [],
        }
        state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(state_json.encode("utf-8")).hexdigest()
        if tamper:
            digest = "0" * 64
        payload = {
            "backupFormat": "riku-football-lab",
            "backupVersion": 3,
            "recordCounts": {"trainings": 1, "measures": 1, "clips": 1, "forms": 0, "matchAnalyses": 0, "aiFormAnalyses": 0},
            "videoFilesIncluded": False,
            "videoFileCount": 1,
            "stateSha256": digest,
            "state": state,
        }
        return {"name": "riku-backup.json", "mimeType": "application/json", "buffer": json.dumps(payload, ensure_ascii=False).encode("utf-8")}

    def test_valid_backup_is_inspected_without_changing_saved_state(self):
        page = self.page
        page.evaluate("localStorage.setItem('preflight-sentinel', 'keep-me')")
        page.locator("#backupInspectFile").set_input_files(self.backup_file())
        page.wait_for_function("document.getElementById('backupInspectStatus').textContent.includes('検査成功')")
        result = page.locator("#backupInspectStatus").inner_text()
        self.assertIn("SHA-256一致", result)
        self.assertIn("練習 1件", result)
        self.assertIn("動画ファイル本体はJSONに含まれません", result)
        self.assertEqual(page.evaluate("localStorage.getItem('preflight-sentinel')"), "keep-me")
        self.assertEqual(page.evaluate("state.trainings.length"), 0)

    def test_checksum_mismatch_is_rejected_without_changing_state(self):
        page = self.page
        page.evaluate("localStorage.setItem('preflight-sentinel', 'keep-me')")
        page.locator("#backupInspectFile").set_input_files(self.backup_file(tamper=True))
        page.wait_for_function("document.getElementById('backupInspectStatus').textContent.includes('検査失敗')")
        self.assertIn("チェックサム不一致", page.locator("#backupInspectStatus").inner_text())
        self.assertEqual(page.evaluate("localStorage.getItem('preflight-sentinel')"), "keep-me")
        self.assertEqual(page.evaluate("state.trainings.length"), 0)

    def test_inspection_ui_is_read_only_and_accessible(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="backupInspectFile"', html)
        self.assertIn('id="backupInspectStatus"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("現在の記録を変更していません", html)


if __name__ == "__main__":
    unittest.main()
