import json
import shutil
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


class RikuBrowserE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required to generate a real browser-playable WebM fixture")
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        cls.video_path = cls.temp_path / "sample.webm"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=lime:s=160x90:d=1:r=12",
                "-an", "-c:v", "libvpx", "-deadline", "realtime",
                "-cpu-used", "8", "-b:v", "120k", str(cls.video_path),
            ],
            check=True,
            timeout=30,
        )
        handler = partial(QuietHandler, directory=str(ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp_dir.cleanup()

    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
        )
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844},
            accept_downloads=True,
        )
        self.page = self.context.new_page()
        self.page.goto(self.base_url, wait_until="load")
        self.page.wait_for_function("typeof saveClip === 'function'")

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    def accept_dialogs(self):
        self.page.on("dialog", lambda dialog: dialog.accept())

    def test_mobile_navigation_accessibility_and_weekly_goal_link(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        self.assertEqual(page.locator("nav.nav").get_attribute("aria-label"), "メインメニュー")
        self.assertGreater(
            page.locator("nav.nav").evaluate("(el) => el.scrollWidth"),
            page.locator("nav.nav").evaluate("(el) => el.clientWidth"),
        )
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"),
            page.evaluate("window.innerWidth") + 2,
        )
        page.locator('.nav button[data-view="video"]').click()
        self.assertTrue(page.locator("#video").evaluate("(el) => el.classList.contains('active')"))
        self.assertEqual(page.locator("#videoMeta").get_attribute("aria-live"), "polite")
        self.assertEqual(page.locator('label[for="videoTitle"]').count(), 1)
        titles = page.evaluate("""() => {
            state.matchAnalyses = [{
                id: 8801, date: today(), title: 'E2E手動確認試合',
                candidateEvents: [{
                    id: 'scene-1', reviewLabel: '陸玖', reviewSource: 'manual',
                    manualGrowthSource: 'manual', manualGrowthFocus: '判断力',
                    assessmentSource: 'manual', assessment: '改善したい',
                    time: 12, availableOptions: ['ドリブル', 'パス']
                }]
            }];
            state.settings.nextMatchGoal = {
                focus: 'ボールを受ける', note: '受ける前に周囲を確認する',
                date: today(), source: 'manual-reviewed-match-growth',
                growthFocus: '判断力'
            };
            persist();
            const timeline = getMatchGrowthTimelineData().find(x => x.key === '判断力');
            return {
                rows: timeline.rows.length,
                plan: getWeeklyCoachPlan().map(x => ({
                    title: x.title,
                    matchGrowthGoal: !!x.sourceMatch?.matchGrowthGoal,
                    growthFocus: x.sourceMatch?.growthFocus || null,
                    note: x.note
                }))
            };
        }""")
        self.assertEqual(titles["rows"], 1)
        self.assertTrue(
            any(item["matchGrowthGoal"] and item["growthFocus"] == "判断力" for item in titles["plan"]),
            json.dumps(titles["plan"], ensure_ascii=False)
        )

    def test_match_and_form_video_save_backup_restore_and_real_playback(self):
        page = self.page
        self.accept_dialogs()
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("E2E 試合動画")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.wait_for_function("document.getElementById('videoMeta').textContent.includes('長さ')", timeout=10000)
        page.get_by_role("button", name="プレー分析を保存").click()
        page.wait_for_function("state.clips.length === 1 && state.clips[0].hasVideo")
        clip_id = page.evaluate("state.clips[0].id")

        page.evaluate("(id) => playSavedClip(id, 0)", clip_id)
        page.wait_for_function("document.getElementById('matchVideo').readyState >= 2", timeout=10000)
        page.evaluate("() => document.getElementById('matchVideo').play()")
        page.wait_for_function("document.getElementById('matchVideo').ended", timeout=10000)

        page.locator('.nav button[data-view="form"]').click()
        page.locator("#formTitle").fill("E2E シュートフォーム")
        page.locator("#formFile").set_input_files(str(self.video_path))
        page.get_by_role("button", name="フォーム分析を保存").click()
        page.wait_for_function("state.forms.length === 1 && state.forms[0].hasVideo")
        form_id = page.evaluate("state.forms[0].id")
        page.evaluate("(id) => playSavedForm(id)", form_id)
        page.wait_for_function("document.getElementById('formVideo').readyState >= 2", timeout=10000)
        page.evaluate("() => document.getElementById('formVideo').play()")
        page.wait_for_function("document.getElementById('formVideo').ended", timeout=10000)

        page.locator('.nav button[data-view="settings"]').click()
        with page.expect_download() as backup_download:
            page.get_by_role("button", name="記録データを書き出す").click()
        backup_path = self.temp_path / "riku-backup.json"
        backup_download.value.save_as(str(backup_path))
        backup = json.loads(backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backup["backupFormat"], "riku-football-lab")
        self.assertFalse(backup["videoFilesIncluded"])
        self.assertEqual(backup["videoFileCount"], 2)

        page.get_by_role("button", name="端末内動画の一覧を作る").click()
        page.wait_for_selector("#videoExportList a[download]")
        export_links = page.locator("#videoExportList a[download]")
        self.assertEqual(export_links.count(), 2)
        exported_paths = []
        for index in range(2):
            with page.expect_download() as video_download:
                export_links.nth(index).click()
            path = self.temp_path / video_download.value.suggested_filename
            video_download.value.save_as(str(path))
            exported_paths.append(path)

        page.evaluate("(id) => removeClipVideo(id)", clip_id)
        page.evaluate("(id) => removeClipVideo('form-' + id)", form_id)
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.length === 1 && state.forms.length === 1")
        page.evaluate("""() => {
            window.__lastVideoImportAlert = '';
            window.alert = message => { window.__lastVideoImportAlert = String(message); };
            window.confirm = () => true;
        }""")
        page.locator("#videoImportFiles").set_input_files([str(x) for x in exported_paths])
        page.wait_for_function(
            "() => window.__lastVideoImportAlert.includes('動画ファイルの復元が完了しました')",
            timeout=10000,
        )
        import_result = page.evaluate("window.__lastVideoImportAlert")
        self.assertIn("新規保存・確認：2本", import_result, import_result)
        restored = page.evaluate("""async ({clipId, formId}) => {
            const clip = await getClipVideo(String(clipId));
            const form = await getClipVideo('form-' + String(formId));
            const keys = await (async () => {
                const db = await openVideoDB();
                try {
                    return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').getAllKeys();
                        req.onsuccess = () => resolve(req.result.map(String));
                        req.onerror = () => reject(req.error);
                    });
                } finally { db.close(); }
            })();
            return {
                clipBytes: clip?.blob instanceof Blob ? clip.blob.size : 0,
                formBytes: form?.blob instanceof Blob ? form.blob.size : 0,
                keys,
                clipFlag: state.clips[0]?.hasVideo,
                formFlag: state.forms[0]?.hasVideo
            };
        }""", {"clipId": clip_id, "formId": form_id})
        self.assertGreater(restored["clipBytes"], 0, json.dumps(restored, ensure_ascii=False))
        self.assertGreater(restored["formBytes"], 0, json.dumps(restored, ensure_ascii=False))
        self.assertTrue(restored["clipFlag"] and restored["formFlag"], json.dumps(restored, ensure_ascii=False))
        clip_restored, form_restored = restored["clipBytes"], restored["formBytes"]
        self.assertEqual(clip_restored, form_restored)

        page.evaluate("(id) => playSavedClip(id, 0)", clip_id)
        page.wait_for_function("document.getElementById('matchVideo').readyState >= 2", timeout=10000)
        page.evaluate("() => document.getElementById('matchVideo').play()")
        page.wait_for_function("document.getElementById('matchVideo').ended", timeout=10000)
        page.evaluate("(id) => playSavedForm(id)", form_id)
        page.wait_for_function("document.getElementById('formVideo').readyState >= 2", timeout=10000)
        page.evaluate("() => document.getElementById('formVideo').play()")
        page.wait_for_function("document.getElementById('formVideo').ended", timeout=10000)

    def test_indexeddb_quota_failure_does_not_create_false_video_record(self):
        page = self.page
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("容量不足テスト")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.evaluate("""() => {
            window.storeClipVideo = async () => {
                throw new DOMException('simulated IndexedDB quota', 'QuotaExceededError');
            };
        }""")
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name="プレー分析を保存").click()
        self.assertEqual(page.evaluate("state.clips.length"), 0)
        self.assertFalse(page.locator("#recordSaveNotice").is_visible())

    def test_localstorage_quota_failure_rolls_back_record_and_shows_warning(self):
        page = self.page
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("記録保存失敗テスト")
        failed = page.evaluate("""() => {
            const original = Storage.prototype.setItem;
            Object.defineProperty(Storage.prototype, 'setItem', {
                configurable: true,
                writable: true,
                value: function(key, value) {
                    if (key === 'rikuFootballLab_v3') {
                        throw new DOMException('simulated localStorage quota', 'QuotaExceededError');
                    }
                    return original.call(this, key, value);
                }
            });
            return persist();
        }""")
        self.assertFalse(failed)
        self.assertFalse(page.locator("#recordSaveNotice").evaluate("(el) => el.classList.contains('hidden')"))
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="プレー分析を保存").click()
        self.assertEqual(page.evaluate("state.clips.length"), 0)
        self.assertFalse(page.locator("#recordSaveNotice").evaluate("(el) => el.classList.contains('hidden')"))

    def test_corrupt_json_backup_is_rejected_without_replacing_current_data(self):
        page = self.page
        page.evaluate("""() => {
            state.settings.name = '保護する現在データ';
            persist();
        }""")
        payload_state = page.evaluate("JSON.parse(JSON.stringify(state))")
        payload_state["settings"]["name"] = "破損したバックアップ"
        bad_backup = {
            "backupFormat": "riku-football-lab",
            "backupVersion": 2,
            "videoFilesIncluded": False,
            "videoFileCount": 0,
            "stateSha256": "0" * 64,
            "state": payload_state,
        }
        bad_path = self.temp_path / "corrupt-backup.json"
        bad_path.write_text(json.dumps(bad_backup, ensure_ascii=False), encoding="utf-8")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#importFile").set_input_files(str(bad_path))
        self.assertEqual(page.evaluate("state.settings.name"), "保護する現在データ")
        self.assertEqual(
            page.evaluate("JSON.parse(localStorage.getItem('rikuFootballLab_v3')).settings.name"),
            "保護する現在データ",
        )

    def test_video_restore_corruption_is_detected_and_rolled_back(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{id: 'restore-check-1', title: '復元照合', hasVideo: false}];
            persist();
            const original = window.storeClipVideo.bind(window);
            window.storeClipVideo = async (key, file) => original(
                key, new Blob([new Uint8Array([1, 2, 3])], {type: file.type})
            );
        }""")
        bad_video = self.temp_path / "riku-video__restore-check-1__sample.webm"
        bad_video.write_bytes(self.video_path.read_bytes())
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#videoImportFiles").set_input_files(str(bad_video))
        page.wait_for_timeout(300)
        page.wait_for_function(
            "getClipVideo('restore-check-1').then(x => x === null)",
            timeout=10000,
        )
        self.assertFalse(page.evaluate("state.clips[0].hasVideo"))



    def test_video_storage_serialization_and_legacy_blob_compatibility(self):
        page = self.page
        result = page.evaluate("""async () => {
            const source = new Blob([new Uint8Array([4, 5, 6, 7])], {type: 'video/mp4'});
            await storeClipVideo('serialized-check', source);
            const db = await openVideoDB();
            let raw;
            try {
                raw = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get('serialized-check');
                    req.onsuccess = () => resolve(req.result);
                    req.onerror = () => reject(req.error);
                });
            } finally { db.close(); }
            const restored = await getClipVideo('serialized-check');
            const legacyBlob = new Blob([new Uint8Array([9, 8, 7])], {type: 'video/webm'});
            const legacyDb = await openVideoDB();
            try {
                await new Promise((resolve, reject) => {
                    const tx = legacyDb.transaction('videos', 'readwrite');
                    tx.objectStore('videos').put({
                        blob: legacyBlob, name: 'legacy.webm', type: 'video/webm', size: 3
                    }, 'legacy-check');
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
            } finally { legacyDb.close(); }
            const legacy = await getClipVideo('legacy-check');
            return {
                rawUsesArrayBuffer: raw?.blobData instanceof ArrayBuffer,
                rawBlobPropertyOmitted: !Object.prototype.hasOwnProperty.call(raw || {}, 'blob'),
                rawName: raw?.name,
                rawSize: raw?.size,
                restoredType: restored?.blob?.type,
                restoredBytes: Array.from(new Uint8Array(await restored.blob.arrayBuffer())),
                legacyBlobReadable: legacy?.blob instanceof Blob,
                legacyBytes: legacy?.blob?.size
            };
        }""")
        self.assertTrue(result["rawUsesArrayBuffer"], result)
        self.assertTrue(result["rawBlobPropertyOmitted"], result)
        self.assertEqual(result["rawName"], "video")
        self.assertEqual(result["rawSize"], 4)
        self.assertEqual(result["restoredType"], "video/mp4")
        self.assertEqual(result["restoredBytes"], [4, 5, 6, 7])
        self.assertTrue(result["legacyBlobReadable"], result)
        self.assertEqual(result["legacyBytes"], 3)

    def test_webkit_safari_compatibility_smoke(self):
        browser = self.playwright.webkit.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof storeClipVideo === 'function' && typeof getClipVideo === 'function'")
            result = page.evaluate("""async () => {
                try {
                    const blob = new Blob([new Uint8Array([7, 8, 9])], {type: 'video/mp4'});
                    await storeClipVideo('webkit-smoke', blob);
                    const saved = await getClipVideo('webkit-smoke');
                    return {
                        opened: true,
                        blobSupported: saved?.blob instanceof Blob,
                        bytes: saved?.blob?.size || 0,
                        quotaApi: !!navigator.storage?.estimate,
                        progress: !!document.getElementById('videoSaveProgressBar'),
                        importProgress: !!document.getElementById('videoImportProgressBar')
                    };
                } catch (error) {
                    return {opened: false, error: String(error)};
                }
            }""")
            self.assertTrue(result.get("opened") and result.get("blobSupported"), result)
            self.assertEqual(result.get("bytes"), 3, result)
            self.assertTrue(result.get("progress") and result.get("importProgress"), result)
            context.close()
        finally:
            browser.close()


    def test_training_reflection_ignores_stale_unconfirmed_and_unlinked_match_evidence(self):
        result = self.page.evaluate("""() => {
            const training = {
                id: 7001, date: '2026-11-01', focus: 'ドリブル',
                steps: ['step'], stepsDone: [],
                linkedMatchEvents: [
                    {matchId: 7002, eventId: 'same-event', assessment: '良かった'},
                    {matchId: 7003, eventId: 'same-event', assessment: '良かった'},
                    {matchId: 7004, eventId: 'old-event', assessment: '改善したい'}
                ]
            };
            state.matchAnalyses = [
                {id: 7002, date: '2026-11-02', candidateEvents: [{
                    id: 'same-event', reviewLabel: '陸玖', reviewSource: 'manual',
                    actionType: 'ドリブル', assessment: '良かった', assessmentSource: 'manual'
                }]},
                {id: 7003, date: '2026-11-02', candidateEvents: [{
                    id: 'same-event', reviewLabel: '別の選手', reviewSource: 'manual',
                    actionType: 'ドリブル', assessment: '良かった', assessmentSource: 'manual'
                }]},
                {id: 7004, date: '2026-10-31', candidateEvents: [{
                    id: 'old-event', reviewLabel: '陸玖', reviewSource: 'manual',
                    actionType: 'ドリブル', assessment: '改善したい', assessmentSource: 'manual'
                }]}
            ];
            const before = getValidatedTrainingMatchEvents(training).map(x => x.id);
            const reflection = buildTrainingReflection(training);
            state.matchAnalyses[0].candidateEvents[0].reviewLabel = '別の選手';
            const afterIdentityChange = getValidatedTrainingMatchEvents(training).length;
            return {before, reflection, afterIdentityChange};
        }""")
        self.assertEqual(result["before"], ["same-event"])
        self.assertIn("連携した試合場面に「良かった」の評価あり", result["reflection"]["good"])
        self.assertEqual(result["afterIdentityChange"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
