import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
SW = (ROOT / "sw.js").read_text(encoding="utf-8")


class Stage44PwaOfflineTests(unittest.TestCase):
    def test_manifest_is_scoped_to_github_pages_project_path(self):
        self.assertEqual("./", MANIFEST["scope"])
        self.assertEqual("./index.html", MANIFEST["start_url"])
        self.assertEqual("standalone", MANIFEST["display"])
        self.assertEqual("ja", MANIFEST["lang"])
        self.assertEqual("./app-icon.svg", MANIFEST["icons"][0]["src"])

    def test_html_links_manifest_icons_and_service_worker(self):
        self.assertIn('<link rel="manifest" href="./manifest.webmanifest">', HTML)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="./app-icon.svg">', HTML)
        self.assertIn('navigator.serviceWorker.register("./sw.js",{scope:"./"})', HTML)
        self.assertIn('id="pwaStatus"', HTML)

    def test_service_worker_caches_only_the_app_shell_files(self):
        for asset in ("./index.html", "./manifest.webmanifest", "./app-icon.svg"):
            self.assertIn(asset, SW)
        self.assertIn("cache.addAll(STATIC_ASSETS)", SW)
        self.assertIn('key.startsWith("riku-football-lab-shell-")', SW)

    def test_navigation_uses_network_first_and_offline_shell_fallback(self):
        self.assertIn('if (request.mode === "navigate")', SW)
        self.assertIn("const response = await fetch(request)", SW)
        self.assertIn("const cached = await caches.match(APP_SHELL)", SW)
        self.assertIn("return cached || Response.error()", SW)

    def test_api_and_video_requests_are_not_intercepted_or_cached(self):
        self.assertIn('if (request.method !== "GET") return;', SW)
        self.assertIn("if (url.origin !== self.location.origin) return;", SW)
        self.assertIn("const staticAsset = STATIC_ASSETS.find", SW)
        self.assertNotIn("request.method === \"POST\"", SW)

    def test_ios_install_instructions_explain_ai_requires_network(self):
        self.assertIn("Safariの共有ボタン", HTML)
        self.assertIn("ホーム画面に追加", HTML)
        self.assertIn("AIサーバーへの動画解析にはインターネット接続が必要", HTML)
        self.assertIn("バックアップも定期的に保存", HTML)


if __name__ == "__main__":
    unittest.main()
