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

    def test_pwa_manifest_service_worker_and_offline_shell(self):
        page = self.page
        manifest = page.evaluate("""async () => {
            const link = document.querySelector('link[rel="manifest"]');
            if (!link) throw new Error("PWA manifest link missing");
            const response = await fetch(link.href);
            if (!response.ok) throw new Error("PWA manifest could not be fetched");
            return response.json();
        }""")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "./")
        self.assertEqual(manifest["start_url"], "./index.html")

        registration = page.evaluate("""async () => {
            if (!("serviceWorker" in navigator)) throw new Error("Service workers unavailable");
            const ready = await navigator.serviceWorker.ready;
            return {active: !!ready.active, scope: ready.scope};
        }""")
        self.assertTrue(registration["active"])
        self.assertTrue(registration["scope"].endswith("/"))

        page.reload(wait_until="load")
        page.wait_for_function("!!navigator.serviceWorker.controller", timeout=10000)
        self.context.set_offline(True)
        try:
            page.reload(wait_until="domcontentloaded", timeout=15000)
            self.assertTrue(page.locator("#home").is_visible())
            self.assertTrue(page.locator(".logo").inner_text().startswith("RIKU"))
        finally:
            self.context.set_offline(False)

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
            "() => window.__lastVideoImportAlert.includes('動画ファイルの復元処理が完了しました')",
            timeout=30000,
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

    def test_match_upload_continues_when_indexeddb_quota_blocks_video_and_resume_saves(self):
        page = self.page
        page.locator('.nav button[data-view="video"]').click()
        page.evaluate("""() => {
            Object.defineProperty(navigator, 'storage', {
                configurable: true,
                value: { estimate: async () => ({ usage: 95, quota: 100 }) }
            });
        }""")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.wait_for_function(
            "document.getElementById('videoMeta').textContent.includes('自動再開はできません')",
            timeout=10000,
        )
        result = page.evaluate("""async () => {
            const requests = [];
            state.settings.apiBaseUrl = 'https://api.test';
            window.getPendingMatchUpload = async () => {
                throw new DOMException('simulated IndexedDB unavailable', 'QuotaExceededError');
            };
            window.savePendingMatchUpload = async () => {
                throw new DOMException('simulated IndexedDB quota', 'QuotaExceededError');
            };
            window.fetch = async (url, options = {}) => {
                const method = options.method || 'GET';
                requests.push({url: String(url), method});
                if (method === 'POST' && String(url).endsWith('/uploads')) {
                    return new Response(JSON.stringify({
                        upload_id: 'quota-fallback-upload',
                        chunk_size: 8,
                        total_chunks: 3
                    }), {status: 200, headers: {'Content-Type': 'application/json'}});
                }
                if (method === 'PUT') return new Response('{}', {status: 200});
                if (method === 'POST' && String(url).endsWith('/complete')) {
                    return new Response(JSON.stringify({job_id: 'quota-fallback-job'}), {
                        status: 200, headers: {'Content-Type': 'application/json'}
                    });
                }
                return new Response('{}', {status: 404});
            };
            const output = document.createElement('div');
            const completed = await uploadMatchVideoInChunks(videoFile.files[0], '10,74', output);
            return {
                jobId: completed.job_id,
                putCount: requests.filter(x => x.method === 'PUT').length,
                initCount: requests.filter(x => x.method === 'POST' && x.url.endsWith('/uploads')).length,
                warning: output.textContent
            };
        }""")
        self.assertEqual(result["jobId"], "quota-fallback-job", result)
        self.assertEqual(result["putCount"], 3, result)
        self.assertEqual(result["initCount"], 1, result)
        self.assertIn("再読み込み後は動画の再選択が必要", result["warning"], result)

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



    def test_video_chunk_write_failure_rolls_back_partial_chunks_and_preserves_previous_video(self):
        page = self.page
        result = page.evaluate("""async () => {
            const originalBlob = new Blob([new Uint8Array([1, 2, 3, 4])], {type: 'video/mp4'});
            await storeClipVideo('rollback-test', originalBlob);
            const originalPut = IDBObjectStore.prototype.put;
            let injected = false;
            IDBObjectStore.prototype.put = function(value, key) {
                if (this.name === 'videoChunks' && String(key || '').startsWith('rollback-test|') && !injected) {
                    injected = true;
                    return originalPut.call(this, value, key);
                }
                if (this.name === 'videoChunks' && String(key || '').startsWith('rollback-test|') && injected) {
                    IDBObjectStore.prototype.put = originalPut;
                    throw new DOMException('simulated quota during second chunk', 'QuotaExceededError');
                }
                return originalPut.call(this, value, key);
            };
            let errorName = '';
            try {
                await storeClipVideo('rollback-test', new Blob([
                    new Uint8Array(1024 * 1024 + 32).fill(9)
                ], {type: 'video/mp4'}));
            } catch (error) { errorName = error.name; }
            finally { IDBObjectStore.prototype.put = originalPut; }
            const restored = await getClipVideo('rollback-test');
            const db = await openVideoDB();
            let keys = [];
            try {
                keys = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').getAllKeys();
                    req.onsuccess = () => resolve(req.result || []);
                    req.onerror = () => reject(req.error);
                });
            } finally { db.close(); }
            return {
                errorName, oldVideoBytes: restored?.blob?.size || 0,
                oldVideoFirstByte: restored?.blob ? new Uint8Array(await restored.blob.arrayBuffer())[0] : null,
                rollbackChunks: keys.filter(key => String(key).startsWith('rollback-test|')).length
            };
        }""")
        self.assertEqual(result["errorName"], "QuotaExceededError", result)
        self.assertEqual(result["oldVideoBytes"], 4, result)
        self.assertEqual(result["oldVideoFirstByte"], 1, result)
        self.assertEqual(result["rollbackChunks"], 1, result)

    def test_video_replacement_cleans_orphaned_generation_chunks(self):
        page = self.page
        result = page.evaluate("""async () => {
            await storeClipVideo('gc-check', new Blob([new Uint8Array([1, 2, 3])], {type: 'video/mp4'}));
            const db = await openVideoDB();
            try {
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readwrite');
                    tx.objectStore('videoChunks').put(new Uint8Array([7, 7]), 'gc-check|abandoned-generation|00000000');
                    const pendingGeneration = Date.now().toString(36) + '-still-writing';
                    tx.objectStore('videoChunks').put(new Uint8Array([8, 8]), 'gc-check|' + pendingGeneration + '|00000000');
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
            } finally { db.close(); }
            await storeClipVideo('gc-check', new Blob([new Uint8Array([4, 5, 6, 7])], {type: 'video/mp4'}));
            const record = await (async () => {
                const d = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = d.transaction('videos', 'readonly'), req = tx.objectStore('videos').get('gc-check');
                    req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
                }); } finally { d.close(); }
            })();
            const d = await openVideoDB();
            try { return await new Promise((resolve, reject) => {
                const tx = d.transaction('videoChunks', 'readonly'), req = tx.objectStore('videoChunks').getAllKeys();
                req.onsuccess = () => resolve({
                    activePrefix: record?.chunkPrefix,
                    keys: (req.result || []).map(String).filter(k => k.startsWith('gc-check|'))
                });
                req.onerror = () => reject(req.error);
            }); } finally { d.close(); }
        }""")
        self.assertEqual(len(result["keys"]), 2, result)
        self.assertTrue(any(key.startswith(result["activePrefix"]) for key in result["keys"]), result)
        self.assertFalse(any("abandoned-generation" in key for key in result["keys"]), result)
        self.assertTrue(any("still-writing" in key for key in result["keys"]), result)

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
            const legacyBuffer = await legacyBlob.arrayBuffer();
            const legacyDb = await openVideoDB();
            try {
                await new Promise((resolve, reject) => {
                    const tx = legacyDb.transaction('videos', 'readwrite');
                    tx.objectStore('videos').put({
                        blobData: legacyBuffer, blobType: 'video/webm', name: 'legacy.webm', type: 'video/webm', size: 3
                    }, 'legacy-check');
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
            } finally { legacyDb.close(); }
            const legacy = await getClipVideo('legacy-check');
            return {
                rawUsesChunkedStorage: raw?.storageFormat === 'chunked-v1',
                rawBlobPropertyOmitted: !Object.prototype.hasOwnProperty.call(raw || {}, 'blob'),
                rawName: raw?.name,
                rawSize: raw?.size,
                restoredType: restored?.blob?.type,
                restoredBytes: Array.from(new Uint8Array(await restored.blob.arrayBuffer())),
                legacyBlobReadable: legacy?.blob instanceof Blob,
                legacyBytes: legacy?.blob?.size
            };
        }""")
        self.assertTrue(result["rawUsesChunkedStorage"], result)
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


    def test_duplicate_or_invalid_training_check_indexes_do_not_inflate_weekly_progress(self):
        result = self.page.evaluate("""() => {
            const training = {
                id: 7101, date: '2026-11-02', focus: 'ドリブル',
                steps: ['one', 'two'],
                stepsDone: [0, 0, 1, 99, -1, '1']
            };
            state.trainings = [training];
            const reflection = buildTrainingReflection(training);
            const cycle = getTrainingCycleSummary(training);
            const weekly = getPreviousWeekTrainingAdjustment('2026-11-03');
            const comparison = getTrainingDecisionComparison(training);
            state.matchAnalyses = [
                {id: 7099, date: '2026-10-30', title: '前回', candidateEvents: []},
                {id: 7100, date: '2026-11-03', title: '今回', candidateEvents: [{
                    id: 'growth-scene', reviewLabel: '陸玖', reviewSource: 'manual',
                    manualGrowthSource: 'manual', manualGrowthFocus: '加速ドリブル',
                    assessmentSource: 'manual', assessment: '良かった', time: 15
                }]}
            ];
            const timeline = getMatchGrowthTimelineData().find(x => x.key === '加速ドリブル');
            return {
                completed: getCompletedTrainingStepIndexes(training),
                good: reflection.good,
                improve: reflection.improve,
                cycle: {stepsDone: cycle.stepsDone, completion: cycle.completion},
                weekly: {assessed: weekly.assessed, avgCompletion: weekly.avgCompletion},
                comparisonDone: comparison.done,
                timelineCompletion: timeline.latest?.trainingNotes?.[0]?.completion
            };
        }""")
        self.assertEqual(result["completed"], [0, 1])
        self.assertIn("2/2項目を実施（100%）", result["good"])
        self.assertFalse(any("チェック未完了" in item for item in result["improve"]))
        self.assertEqual(result["cycle"], {"stepsDone": 2, "completion": 100})
        self.assertEqual(result["weekly"], {"assessed": 1, "avgCompletion": 100})
        self.assertEqual(result["comparisonDone"], 2)
        self.assertEqual(result["timelineCompletion"], 100)


    def test_match_event_link_save_failure_restores_previous_links(self):
        result = self.page.evaluate("""() => {
            state.trainings = [{
                id: 7201, date: '2026-11-01', menu: '親子ドリブル',
                focus: 'ドリブル', steps: ['step'], stepsDone: [],
                linkedMatchEvents: [{
                    matchId: 7200, eventId: 'old-event', matchDate: '2026-10-30',
                    matchTitle: '以前の試合', actionType: 'ドリブル', autoLinked: true
                }]
            }];
            state.matchAnalyses = [{
                id: 7200, date: '2026-11-02', title: '連携保存失敗テスト',
                candidateEvents: [{
                    id: 'new-event', reviewLabel: '陸玖', reviewSource: 'manual',
                    actionType: 'ドリブル', time: 20
                }]
            }];
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
            window.__linkAlert = '';
            window.alert = message => { window.__linkAlert = String(message); };
            linkMatchEventToTraining(7200, 'new-event');
            return {
                links: state.trainings[0].linkedMatchEvents.map(x => ({
                    matchId: x.matchId, eventId: x.eventId
                })),
                alert: window.__linkAlert
            };
        }""")
        self.assertEqual(result["links"], [{"matchId": 7200, "eventId": "old-event"}])
        self.assertIn("元の練習記録と連携状態に戻しました", result["alert"])


    def test_match_scan_saved_before_local_video_links_and_opens_playback(self):
        page = self.page
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("同一動画の試合分析")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.evaluate("""() => {
            window.alert = () => {};
            const result = {
                requested_jersey_numbers: "10,74",
                summary: {
                    duration_seconds: 1,
                    sampled_pose_frames: 2,
                    candidate_events: [{
                        id: "linked-scene", time_seconds: 0.5,
                        label: "動きの変化", reason: "映像上の候補",
                        clip_available: false, review_label: "未確認"
                    }]
                }
            };
            document.getElementById("matchAiResult").dataset.result = JSON.stringify(result);
            saveMatchScanResult();
        }""")
        self.assertEqual(page.evaluate("state.matchAnalyses.length"), 1)
        self.assertIsNone(page.evaluate("state.matchAnalyses[0].clipId"))
        page.evaluate("saveClip()")
        page.wait_for_function("state.clips.length === 1 && state.clips[0].hasVideo")
        linked = page.evaluate("""() => ({
            clipId: String(state.clips[0].id),
            matchId: String(state.matchAnalyses[0].id),
            matchClipId: String(state.matchAnalyses[0].clipId),
            storageKey: state.matchAnalyses[0].videoStorageKey,
            matchIds: state.clips[0].matchAnalysisIds.map(String),
            fingerprint: !!state.matchAnalyses[0].sourceVideoKey
        })""")
        self.assertEqual(linked["matchClipId"], linked["clipId"], linked)
        self.assertEqual(linked["storageKey"], linked["clipId"], linked)
        self.assertIn(linked["matchId"], linked["matchIds"], linked)
        self.assertTrue(linked["fingerprint"], linked)
        page.evaluate("renderMatchLibrary()")
        self.assertIn("端末内動画を再生", page.locator("#matchLibrary").inner_text())
        page.get_by_role("button", name="端末内動画を再生").first.click()
        page.wait_for_function("document.getElementById('matchVideo').readyState >= 2", timeout=10000)


    def test_positioning_summary_and_weekly_plan_use_only_confirmed_manual_reviews(self):
        result = self.page.evaluate("""() => {
            state.trainings = [];
            state.settings = {...(state.settings || {}), nextMatchGoal: null};
            state.matchAnalyses = [
                {
                    id: 9301, date: today(), title: 'ポジショニング確認1',
                    candidateEvents: [
                        {id: 'p1', reviewLabel: '陸玖', reviewSource: 'manual',
                         positioningReview: {scanBeforeReceive: '改善したい'}},
                        {id: 'p2', reviewLabel: '陸玖', reviewSource: 'manual',
                         positioningReview: {scanBeforeReceive: '改善したい'}},
                        {id: 'not-confirmed', reviewLabel: '未確認', reviewSource: null,
                         positioningReview: {scanBeforeReceive: '改善したい'}}
                    ]
                },
                {
                    id: 9302, date: today(), title: 'ポジショニング確認2',
                    candidateEvents: [
                        {id: 'p3', reviewLabel: '陸玖', reviewSource: 'manual',
                         positioningReview: {scanBeforeReceive: '良かった'}},
                        {id: 'not-visible', reviewLabel: '陸玖', reviewSource: 'manual',
                         positioningReview: {scanBeforeReceive: '映像で確認できない'}},
                        {id: 'other-player', reviewLabel: '別の選手', reviewSource: 'manual',
                         positioningReview: {scanBeforeReceive: '改善したい'}}
                    ]
                }
            ];
            const profile = getMatchPositioningAnalysis();
            const row = profile.rows.find(x => x.key === 'scanBeforeReceive');
            const plan = getWeeklyCoachPlan()[0];
            const saved = persist();
            return {
                assessed: row.assessed,
                good: row.good,
                improve: row.improve,
                matchCount: row.matchCount,
                priority: profile.priority?.key || null,
                planIssue: plan.sourceMatch?.positioningIssue || null,
                saved
            };
        }""")
        self.assertEqual(result["assessed"], 3, result)
        self.assertEqual(result["good"], 1, result)
        self.assertEqual(result["improve"], 2, result)
        self.assertEqual(result["matchCount"], 2, result)
        self.assertEqual(result["priority"], "scanBeforeReceive", result)
        self.assertEqual(result["planIssue"], "scanBeforeReceive", result)
        self.assertTrue(result["saved"], result)


    def test_positioning_review_save_failure_restores_original_value(self):
        result = self.page.evaluate("""() => {
            state.matchAnalyses = [{
                id: 9401, date: today(), title: '評価保存失敗',
                candidateEvents: [{
                    id: 'position-event', reviewLabel: '陸玖', reviewSource: 'manual',
                    positioningReview: {scanBeforeReceive: '良かった'}
                }]
            }];
            const event = state.matchAnalyses[0].candidateEvents[0];
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
            window.__positioningAlert = '';
            window.alert = message => { window.__positioningAlert = String(message); };
            updateMatchPositioning(9401, 'position-event', 'scanBeforeReceive', '改善したい');
            return {
                value: event.positioningReview.scanBeforeReceive,
                alert: window.__positioningAlert
            };
        }""")
        self.assertEqual(result["value"], "良かった", result)
        self.assertIn("保存できませんでした", result["alert"])


    def test_deleting_match_history_cleans_links_but_preserves_training_snapshot(self):
        result = self.page.evaluate("""() => {
            window.confirm = () => true;
            window.alert = () => {};
            state.matchAnalyses = [
                {id: '9501', date: '2026-11-02', title: '削除する試合', candidateEvents: []},
                {id: 9502, date: '2026-11-03', title: '残す試合', candidateEvents: []}
            ];
            state.trainings = [
                {
                    id: 9503, date: '2026-11-01', menu: '判断練習', focus: 'ボールを受ける',
                    linkedMatchEvents: [
                        {matchId: 9501, eventId: 'deleted-event'},
                        {matchId: 9502, eventId: 'kept-event'}
                    ],
                    sourceMatch: {
                        matchId: '9501', eventId: 'deleted-event',
                        matchTitle: '削除する試合', note: '本人確認済みの改善課題'
                    }
                }
            ];
            deleteMatchScan(9501);
            const training = state.trainings[0];
            return {
                remainingMatches: state.matchAnalyses.map(x => String(x.id)),
                links: training.linkedMatchEvents.map(x => String(x.matchId) + ':' + x.eventId),
                sourceMatchId: training.sourceMatch.matchId,
                sourceDeleted: training.sourceMatch.matchRecordDeleted,
                sourceSnapshot: training.sourceMatch.matchTitle,
                followup: getImprovementFollowup(training)
            };
        }""")
        self.assertEqual(result["remainingMatches"], ["9502"], result)
        self.assertEqual(result["links"], ["9502:kept-event"], result)
        self.assertEqual(result["sourceMatchId"], "9501", result)
        self.assertTrue(result["sourceDeleted"], result)
        self.assertEqual(result["sourceSnapshot"], "削除する試合", result)
        self.assertIsNone(result["followup"], result)


    def test_match_history_delete_failure_rolls_back_match_and_training_links(self):
        result = self.page.evaluate("""() => {
            window.confirm = () => true;
            window.__deleteMatchAlert = '';
            window.alert = message => { window.__deleteMatchAlert = String(message); };
            state.matchAnalyses = [
                {id: 9601, date: '2026-11-02', title: '保存失敗する試合', candidateEvents: []}
            ];
            state.trainings = [{
                id: 9602, date: '2026-11-01', menu: '判断練習', focus: 'ボールを受ける',
                linkedMatchEvents: [{matchId: 9601, eventId: 'linked-event'}],
                sourceMatch: {matchId: 9601, eventId: 'linked-event', matchTitle: '保存失敗する試合'}
            }];
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
            deleteMatchScan(9601);
            const training = state.trainings[0];
            return {
                matchIds: state.matchAnalyses.map(x => String(x.id)),
                links: training.linkedMatchEvents.map(x => String(x.matchId) + ':' + x.eventId),
                sourceDeleted: !!training.sourceMatch.matchRecordDeleted,
                alert: window.__deleteMatchAlert
            };
        }""")
        self.assertEqual(result["matchIds"], ["9601"], result)
        self.assertEqual(result["links"], ["9601:linked-event"], result)
        self.assertFalse(result["sourceDeleted"], result)
        self.assertIn("元の状態に戻しました", result["alert"])


    def test_webkit_settings_backup_export_and_restore_interaction(self):
        browser = self.playwright.webkit.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            accept_downloads=True,
        )
        page = context.new_page()
        try:
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof exportData === 'function' && typeof getClipVideo === 'function'")
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator('.nav button[data-view="settings"]').click()
            self.assertTrue(page.locator("#settings").evaluate("(el) => el.classList.contains('active')"))
            with page.expect_download(timeout=15000) as download_info:
                page.get_by_role("button", name="記録データを書き出す").click()
            download = download_info.value
            self.assertIn("riku-football-lab-backup-", download.suggested_filename)

            backup_text = page.evaluate("""async () => {
                const snapshot = {
                    ...state,
                    settings: {...state.settings},
                    trainings: [{id: 98101, date: '2026-11-03', focus: 'ドリブル', steps: ['加速'], stepsDone: [0]}],
                    measures: Array.isArray(state.measures) ? state.measures : [],
                    clips: [], forms: [],
                    matchAnalyses: [{id: 98102, date: '2026-11-03', title: 'Safari restore', candidateEvents: []}],
                    aiFormAnalyses: []
                };
                const serialized = JSON.stringify(snapshot);
                const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(serialized));
                const stateSha256 = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
                return JSON.stringify({
                    backupFormat: 'riku-football-lab',
                    backupVersion: 3,
                    recordCounts: {trainings: 1, measures: snapshot.measures.length, clips: 0, forms: 0, matchAnalyses: 1, aiFormAnalyses: 0},
                    videoFilesIncluded: false,
                    videoFileCount: 0,
                    stateSha256,
                    state: snapshot
                });
            }""")
            page.locator("#importFile").set_input_files({
                "name": "riku-safari-backup.json",
                "mimeType": "application/json",
                "buffer": backup_text.encode("utf-8")
            })
            page.wait_for_function("state.trainings.some(x => x.id === 98101) && state.matchAnalyses.some(x => x.id === 98102)")
            result = page.evaluate("""() => ({
                training: state.trainings.find(x => x.id === 98101)?.stepsDone,
                match: state.matchAnalyses.find(x => x.id === 98102)?.title,
                stored: JSON.parse(localStorage.getItem(KEY)).trainings.some(x => x.id === 98101)
            })""")
            self.assertEqual(result["training"], [0], result)
            self.assertEqual(result["match"], "Safari restore", result)
            self.assertTrue(result["stored"], result)
        finally:
            context.close()
            browser.close()


    def test_match_video_chunk_upload_15_and_20_minute_contract(self):
        page = self.page
        result = page.evaluate("""async () => {
            state.settings.apiBaseUrl = 'https://upload.test';
            const received = [];
            const initPayloads = [];
            let completed = 0;
            let activeUploadId = '';
            window.fetch = async (url, options = {}) => {
                const path = new URL(url).pathname;
                if (path === '/analyze/match/uploads' && options.method === 'POST') {
                    const payload = JSON.parse(options.body);
                    initPayloads.push(payload);
                    activeUploadId = 'synthetic-' + initPayloads.length;
                    return new Response(JSON.stringify({
                        ok: true, upload_id: activeUploadId, chunk_size: 6 * 1024 * 1024,
                        total_chunks: Math.ceil(payload.size_bytes / (6 * 1024 * 1024))
                    }), {status: 201, headers: {'Content-Type': 'application/json'}});
                }
                const chunk = path.match(/\/analyze\/match\/uploads\/(synthetic-\d+)\/(\d+)$/);
                if (chunk && options.method === 'PUT') {
                    const part = options.body.get('file');
                    received.push({upload: chunk[1], index: Number(chunk[2]), size: part.size});
                    return new Response(JSON.stringify({ok: true}), {
                        status: 200, headers: {'Content-Type': 'application/json'}
                    });
                }
                if (path.endsWith('/complete') && options.method === 'POST') {
                    completed++;
                    return new Response(JSON.stringify({ok: true, job_id: 'job-' + completed}),
                        {status: 202, headers: {'Content-Type': 'application/json'}});
                }
                throw new Error('Unexpected upload request: ' + options.method + ' ' + path);
            };
            const cases = [
                {duration: 900, bytes: 7 * 1024 * 1024 + 11, name: 'synthetic-15min.mp4'},
                {duration: 1200, bytes: 13 * 1024 * 1024 + 123, name: 'synthetic-20min.mp4'}
            ];
            const results = [];
            for (const item of cases) {
                Object.defineProperty(document.getElementById('matchVideo'), 'duration', {
                    configurable: true, value: item.duration
                });
                const file = new File([new Uint8Array(item.bytes)], item.name, {type: 'video/mp4'});
                const status = document.createElement('div');
                const response = await uploadMatchVideoInChunks(file, ['10','74'], status);
                results.push({duration: item.duration, size: file.size, response, status: status.textContent});
            }
            return {initPayloads, received, completed, results};
        }""")
        self.assertEqual([x["duration_seconds"] for x in result["initPayloads"]], [900, 1200], result)
        self.assertEqual([x["size_bytes"] for x in result["initPayloads"]],
                         [7 * 1024 * 1024 + 11, 13 * 1024 * 1024 + 123], result)
        self.assertEqual([x["index"] for x in result["received"]], [0, 1, 0, 1, 2], result)
        self.assertEqual(
            [sum(x["size"] for x in result["received"] if x["upload"] == upload)
             for upload in ("synthetic-1", "synthetic-2")],
            [7 * 1024 * 1024 + 11, 13 * 1024 * 1024 + 123], result
        )
        self.assertTrue(all(x["size"] <= 6 * 1024 * 1024 for x in result["received"]), result)
        self.assertEqual(result["completed"], 2, result)
        self.assertEqual([x["response"]["job_id"] for x in result["results"]], ["job-1", "job-2"], result)



    def test_15_and_20_minute_match_upload_frontend_completion_flow(self):
        page = self.page
        self.accept_dialogs()
        page.locator('.nav button[data-view="video"]').click()
        page.evaluate("""() => {
            state.settings.apiBaseUrl = 'https://riku-upload-mock.invalid';
            persist();
        }""")

        counters = {"created": 0, "chunks": 0, "completed": 0, "status": 0}
        def mock_api(route):
            request = route.request
            path = request.url.split("riku-upload-mock.invalid", 1)[-1]
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
            if request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
            elif path == "/health":
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True}))
            elif path == "/analyze/match/uploads" and request.method == "POST":
                counters["created"] += 1
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True, "upload_id": "mock-upload",
                                               "chunk_size": 6 * 1024 * 1024,
                                               "total_chunks": request.post_data_json["size_bytes"] // (6 * 1024 * 1024) +
                                               (1 if request.post_data_json["size_bytes"] % (6 * 1024 * 1024) else 0)}))
            elif path.startswith("/analyze/match/uploads/mock-upload/") and request.method == "PUT":
                counters["chunks"] += 1
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True}))
            elif path == "/analyze/match/uploads/mock-upload/complete" and request.method == "POST":
                counters["completed"] += 1
                route.fulfill(status=202, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True, "job_id": "mock-job", "status": "queued"}))
            elif path == "/analyze/jobs/mock-job":
                counters["status"] += 1
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"status": "completed", "progress": 100, "stage": "完了",
                                               "result": {"job_id": "mock-job", "summary": {
                                                   "duration_seconds": 900, "sampled_pose_frames": 0,
                                                   "feedback": [], "candidate_events": [],
                                                   "person_detection_summary": {},
                                                   "person_track_summary": {},
                                                   "jersey_ocr_summary": {},
                                               }}}))
            else:
                route.fulfill(status=404, headers=headers, content_type="application/json",
                              body=json.dumps({"detail": "unexpected mock request: " + path}))
        page.route("https://riku-upload-mock.invalid/**", mock_api)

        for duration, size in ((900, 7 * 1024 * 1024 + 11), (1200, 13 * 1024 * 1024 + 123)):
            page.evaluate("""(seconds) => {
                const video = document.getElementById('matchVideo');
                Object.defineProperty(video, 'duration', {configurable: true, value: seconds});
            }""", duration)
            page.locator("#videoFile").set_input_files({
                "name": f"synthetic-{duration}.mp4",
                "mimeType": "video/mp4",
                "buffer": b"R" * size,
            })
            page.get_by_role("button", name="AIサーバーで動画解析").click()
            page.wait_for_function(
                "() => document.getElementById('matchAiResult').textContent.includes('全編スキャンが完了しました')",
                timeout=30000,
            )
            self.assertTrue(page.locator("#video").evaluate("(el) => el.classList.contains('active')"))
            page.evaluate("() => { document.getElementById('videoFile').value = ''; }")
        self.assertEqual(counters["created"], 2)
        self.assertEqual(counters["completed"], 2)
        self.assertEqual(counters["status"], 2)
        self.assertGreaterEqual(counters["chunks"], 5)


    def test_match_analysis_save_waits_for_pending_video_file(self):
        page = self.page
        self.accept_dialogs()
        result = page.evaluate("""async () => {
            state.matchAnalyses = [];
            state.clips = [];
            state.forms = [];
            state.aiFormAnalyses = [];
            const resultElement = document.getElementById('matchAiResult');
            resultElement.dataset.result = JSON.stringify({
                job_id: 'delayed-save-job',
                requested_jersey_numbers: '10,74',
                summary: {duration_seconds: 900, sampled_pose_frames: 0, frames: [],
                          candidate_events: [], feedback: []}
            });
            document.getElementById('videoTitle').value = '';
            let release;
            pendingMatchSave = new Promise(resolve => { release = resolve; });
            const file = new File([new Uint8Array([1, 2, 3])], 'delayed-match.mp4',
                                  {type: 'video/mp4', lastModified: 1234});
            const expectedKey = getVideoSourceKey(file);
            const saving = saveMatchScanResult();
            await new Promise(resolve => setTimeout(resolve, 0));
            const countBeforePendingSave = state.matchAnalyses.length;
            release(file);
            await saving;
            return {
                countBeforePendingSave,
                sourceVideoKey: state.matchAnalyses[0]?.sourceVideoKey || '',
                title: state.matchAnalyses[0]?.title || '',
                expectedKey
            };
        }""")
        self.assertEqual(result["countBeforePendingSave"], 0, result)
        self.assertEqual(result["sourceVideoKey"], result["expectedKey"], result)
        self.assertEqual(result["title"], "delayed-match.mp4", result)


    def test_webkit_resumes_saved_match_upload_after_page_reload(self):
        browser = self.playwright.webkit.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        page = context.new_page()
        try:
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof uploadMatchVideoInChunks === 'function'")
            page.locator('.nav button[data-view="video"]').click()
            page.evaluate("""() => { state.settings.apiBaseUrl = 'https://riku-resume-mock.invalid'; persist(); }""")
            page.locator("#videoFile").set_input_files({
                "name": "resume-after-reload.mp4", "mimeType": "video/mp4",
                "buffer": b"R" * (6 * 1024 * 1024 + 23),
            })
            page.wait_for_function("() => document.getElementById('videoFile').files.length === 1")
            original = page.evaluate("""async () => {
                const file = document.getElementById('videoFile').files[0];
                await storeClipVideo('__pending_match_video__', file);
                await savePendingMatchUpload({sourceKey:getVideoSourceKey(file),size:file.size,
                    name:file.name,lastModified:file.lastModified,jerseyNumbers:'10,74',
                    uploadId:'resume-upload',chunkSize:6*1024*1024,totalChunks:2,nextChunk:1,createdAt:Date.now()});
                return {size:file.size,sourceKey:getVideoSourceKey(file)};
            }""")
            page.reload(wait_until="load")
            page.wait_for_function("typeof uploadMatchVideoInChunks === 'function'")
            counters = {"status": 0, "created": 0, "puts": [], "completed": 0}
            def mock_api(route):
                request = route.request
                if not request.url.startswith("https://riku-resume-mock.invalid/"):
                    route.continue_()
                    return
                path = request.url.split("riku-resume-mock.invalid", 1)[-1]
                headers = {"Access-Control-Allow-Origin":"*",
                           "Access-Control-Allow-Methods":"GET, POST, PUT, DELETE, OPTIONS",
                           "Access-Control-Allow-Headers":"*"}
                if request.method == "OPTIONS":
                    route.fulfill(status=204, headers=headers)
                elif path == "/analyze/match/uploads/resume-upload" and request.method == "GET":
                    counters["status"] += 1
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"upload_id":"resume-upload",
                                                   "next_chunk":1,"total_chunks":2,
                                                   "received_bytes":6*1024*1024,
                                                   "total_bytes":original["size"],"complete":False}))
                elif path == "/analyze/match/uploads/resume-upload/1" and request.method == "PUT":
                    counters["puts"].append(1)
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"chunk_index":1}))
                elif path == "/analyze/match/uploads/resume-upload/complete" and request.method == "POST":
                    counters["completed"] += 1
                    route.fulfill(status=202, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"job_id":"resume-job","status":"queued"}))
                else:
                    route.fulfill(status=404, headers=headers, content_type="application/json",
                                  body=json.dumps({"detail":"unexpected request: "+path}))
            page.route("**/*", mock_api)
            result = page.evaluate("""async () => {
                const stored = await getClipVideo('__pending_match_video__');
                if (!stored || !(stored.blob instanceof Blob)) throw new Error('saved source video missing after reload');
                const file = new File([stored.blob], stored.name, {type:stored.type, lastModified:stored.lastModified});
                const response = await uploadMatchVideoInChunks(file, '10,74', document.getElementById('matchAiResult'));
                return {jobId:response.job_id,size:file.size,pending:await getPendingMatchUpload()};
            }""")
            self.assertEqual(result["jobId"], "resume-job", result)
            self.assertEqual(result["size"], original["size"], result)
            self.assertIsNone(result["pending"], result)
            self.assertEqual(counters, {"status":1,"created":0,"puts":[1],"completed":1})
        finally:
            context.close()
            browser.close()

    def test_webkit_15_minute_match_upload_frontend_completion_flow(self):
        browser = self.playwright.webkit.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof saveClip === 'function'")
            page.locator('.nav button[data-view="video"]').click()
            page.evaluate("""() => {
                state.settings.apiBaseUrl = 'https://riku-webkit-mock.invalid';
                persist();
            }""")
            counters = {"created": 0, "chunks": 0, "completed": 0, "status": 0}
            def mock_api(route):
                request = route.request
                if not request.url.startswith("https://riku-webkit-mock.invalid/"):
                    route.continue_()
                    return
                path = request.url.split("riku-webkit-mock.invalid", 1)[-1]
                headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-Requested-With",
                    "Access-Control-Max-Age": "86400",
                }
                if request.method == "OPTIONS":
                    route.fulfill(status=204, headers=headers)
                elif path == "/health":
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True}))
                elif path == "/analyze/match/uploads" and request.method == "POST":
                    counters["created"] += 1
                    size = request.post_data_json["size_bytes"]
                    chunk_size = 6 * 1024 * 1024
                    route.fulfill(status=201, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "upload_id": "webkit-upload",
                                                   "chunk_size": chunk_size,
                                                   "total_chunks": (size + chunk_size - 1) // chunk_size}))
                elif path.startswith("/analyze/match/uploads/webkit-upload/") and request.method == "PUT":
                    counters["chunks"] += 1
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True}))
                elif path == "/analyze/match/uploads/webkit-upload/complete" and request.method == "POST":
                    counters["completed"] += 1
                    route.fulfill(status=202, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "job_id": "webkit-job", "status": "queued"}))
                elif path == "/analyze/jobs/webkit-job":
                    counters["status"] += 1
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"status": "completed", "progress": 100, "stage": "完了",
                                                   "result": {"job_id": "webkit-job", "summary": {
                                                       "duration_seconds": 900, "sampled_pose_frames": 0,
                                                       "feedback": [], "candidate_events": [],
                                                       "person_detection_summary": {},
                                                       "person_track_summary": {},
                                                       "jersey_ocr_summary": {},
                                                   }}}))
                else:
                    route.fulfill(status=404, headers=headers, content_type="application/json",
                                  body=json.dumps({"detail": "unexpected mock request: " + path}))
            page.route("**/*", mock_api)
            page.locator("#videoFile").set_input_files({
                "name": "webkit-synthetic-15min.mp4",
                "mimeType": "video/mp4",
                "buffer": b"W" * (7 * 1024 * 1024 + 19),
            })
            # AI upload uses the selected File directly. Do not block this test on
            # the independent IndexedDB background-save promise.
            page.wait_for_function(
                "() => document.getElementById('videoFile').files.length === 1",
                timeout=5000,
            )
            page.evaluate("""() => {
                Object.defineProperty(document.getElementById('matchVideo'), 'duration',
                                      {configurable: true, value: 900});
            }""")
            page.get_by_role("button", name="AIサーバーで動画解析").click()
            try:
                page.wait_for_function(
                    "() => document.getElementById('matchAiResult').textContent.includes('全編スキャンが完了しました')",
                    timeout=30000,
                )
            except Exception as error:
                diagnostic = page.evaluate("""() => ({
                    result: document.getElementById('matchAiResult').textContent,
                    videoMeta: document.getElementById('videoMeta').textContent,
                    apiBaseUrl: state.settings.apiBaseUrl
                })""")
                raise AssertionError({"diagnostic": diagnostic, "counters": counters, "cause": str(error)})
            self.assertTrue(page.locator("#video").evaluate("(el) => el.classList.contains('active')"))
            self.assertEqual(counters["created"], 1)
            self.assertEqual(counters["completed"], 1)
            self.assertEqual(counters["status"], 1)
            self.assertGreaterEqual(counters["chunks"], 2)
        finally:
            context.close()
            browser.close()



if __name__ == "__main__":
    unittest.main(verbosity=2)
