import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage45DeviceStorageTests(unittest.TestCase):
    def test_settings_expose_online_and_storage_status(self):
        self.assertIn('id="connectionStatus"', HTML)
        self.assertIn('id="deviceStorageStatus"', HTML)
        self.assertIn('onclick="refreshDeviceStorageStatus()"', HTML)

    def test_connection_status_tracks_online_and_offline_events(self):
        self.assertIn('window.addEventListener("online",renderConnectionStatus)', HTML)
        self.assertIn('window.addEventListener("offline",renderConnectionStatus)', HTML)
        self.assertIn("navigator.onLine!==false", HTML)
        self.assertIn("端末内の保存済み記録を利用できます", HTML)

    def test_storage_estimate_is_feature_detected_and_approximate(self):
        self.assertIn("navigator.storage.estimate", HTML)
        self.assertIn("const estimate=await navigator.storage.estimate()", HTML)
        self.assertIn("このサイトの保存領域の目安：", HTML)
        self.assertIn("保存容量はブラウザが返す概算です", HTML)

    def test_persistent_storage_requires_user_action_and_feature_detection(self):
        self.assertIn('onclick="requestPersistentStorage()"', HTML)
        self.assertIn("navigator.storage.persist", HTML)
        self.assertIn("const granted=await navigator.storage.persist()", HTML)
        self.assertIn("定期的なバックアップ", HTML)

    def test_storage_failure_has_safe_fallback_message(self):
        self.assertIn("このブラウザでは保存容量の概算を取得できません", HTML)
        self.assertIn("保存容量を取得できませんでした", HTML)
        self.assertIn("保存データの保護状態を確認できませんでした", HTML)

    def test_initial_status_refresh_runs_on_page_load(self):
        self.assertIn('window.addEventListener("load",()=>{', HTML)
        self.assertIn("renderConnectionStatus();", HTML)
        self.assertIn("refreshDeviceStorageStatus();", HTML)

    def test_runtime_status_script_is_at_document_end(self):
        self.assertLess(HTML.rfind("function renderConnectionStatus"), HTML.rfind("</body>"))
        self.assertGreater(HTML.rfind("function renderConnectionStatus"), HTML.rfind("</script>", 0, HTML.rfind("function renderConnectionStatus")))

    def test_ai_analysis_network_requirement_is_preserved(self):
        self.assertIn("AIサーバー解析には通信が必要です", HTML)
        self.assertIn("AIサーバーへの動画解析にはインターネット接続が必要", HTML)


if __name__ == "__main__":
    unittest.main()
