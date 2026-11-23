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

    def wait_for_stage48_restore(self, timeout=30000):
        self.page.wait_for_function("""() => {
            const text = document.getElementById('stage48Status')?.textContent || '';
            return /全動画の復元とSHA-256照合が完了|完了（一部失敗）|安全停止した動画があります|再開対象がありません/.test(text);
        }""", timeout=timeout)

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
            const uploadFile = new File([new Uint8Array(12 * 1024 * 1024 + 1)], 'quota-large.mp4', {type:'video/mp4'});
            const totalBytes = uploadFile.size;
            const chunkSize = 6 * 1024 * 1024;
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
                        ok: true, upload_id: 'quota-fallback-upload',
                        chunk_size: chunkSize,
                        total_chunks: Math.ceil(totalBytes / chunkSize)
                    }), {status: 201, headers: {'Content-Type': 'application/json'}});
                }
                if (method === 'PUT') {
                    const index = Number(String(url).split('/').pop());
                    return new Response(JSON.stringify({
                        ok: true, chunk_index: index,
                        received_bytes: Math.min(totalBytes, (index + 1) * chunkSize),
                        total_bytes: totalBytes
                    }), {status: 200, headers: {'Content-Type': 'application/json'}});
                }
                if (method === 'POST' && String(url).endsWith('/complete')) {
                    return new Response(JSON.stringify({job_id: 'quota-fallback-job'}), {
                        status: 200, headers: {'Content-Type': 'application/json'}
                    });
                }
                return new Response('{}', {status: 404});
            };
            const output = document.createElement('div');
            const completed = await uploadMatchVideoInChunks(uploadFile, '10,74', output);
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
                    tx.objectStore('videoChunks').put(new Uint8Array([7, 7]), 'gc-check|00000000-abandoned-generation|00000000');
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

    def test_video_record_delete_rolls_back_when_local_record_persistence_fails(self):
        page = self.page
        page.evaluate("""async () => {
            const blob = new Blob([new Uint8Array([1, 2, 3, 4])], {type: 'video/mp4'});
            await storeClipVideo('delete-rollback-1', blob);
            state.clips = [{id: 'delete-rollback-1', title: '削除保護', hasVideo: true}];
            persist();
            const originalSetItem = Storage.prototype.setItem;
            Storage.prototype.setItem = function(key, value) {
                if (key === 'rikuFootballLab_v3') throw new DOMException('simulated quota', 'QuotaExceededError');
                return originalSetItem.call(this, key, value);
            };
            window.__restoreStorageSetItem = () => { Storage.prototype.setItem = originalSetItem; };
        }""")
        page.once("dialog", lambda dialog: dialog.accept())
        page.evaluate("deleteItem('clips', 'delete-rollback-1')")
        page.evaluate("window.__restoreStorageSetItem()")
        result = page.evaluate("""async () => ({
            recordExists: state.clips.some(x => String(x.id) === 'delete-rollback-1'),
            videoBytes: (await getClipVideo('delete-rollback-1'))?.blob?.size || 0
        })""")
        self.assertTrue(result["recordExists"], result)
        self.assertEqual(result["videoBytes"], 4, result)


    def test_video_import_rejects_file_that_does_not_match_record_identity(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{
                id: 'import-identity-1', title: '元動画照合',
                hasVideo: false, sourceVideoKey: 'original.mp4|4|123|video/mp4'
            }];
            persist();
        }""")
        wrong_video = self.temp_path / "riku-video__import-identity-1__original.mp4"
        wrong_video.write_bytes(b"wrong-size")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#videoImportFiles").set_input_files(str(wrong_video))
        self.wait_for_stage48_restore()
        result = page.evaluate("""async () => ({
            hasVideo: state.clips[0].hasVideo,
            stored: await getClipVideo('import-identity-1')
        })""")
        self.assertFalse(result["hasVideo"], result)
        self.assertIsNone(result["stored"])


    def test_video_export_keeps_valid_files_when_one_saved_video_is_corrupt(self):
        result = self.page.evaluate("""async () => {
            await storeClipVideo('export-good', new Blob([
                new Uint8Array([1, 2, 3, 4])
            ], {type: 'video/mp4'}));
            await storeClipVideo('export-bad', new Blob([
                new Uint8Array([5, 6, 7, 8])
            ], {type: 'video/mp4'}));
            const db = await openVideoDB();
            try {
                const record = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get('export-bad');
                    req.onsuccess = () => resolve(req.result);
                    req.onerror = () => reject(req.error);
                });
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readwrite');
                    tx.objectStore('videoChunks').delete(
                        record.chunkPrefix + '00000000'
                    );
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
            } finally { db.close(); }
            await prepareVideoExport();
            const host = document.getElementById('videoExportList');
            return {
                text: host.textContent,
                links: [...host.querySelectorAll('a[download]')].map(a => a.download),
                hasGood: host.textContent.includes('export-good'),
                hasBadWarning: host.textContent.includes('export-bad')
            };
        }""")
        self.assertTrue(result["hasGood"], result)
        self.assertTrue(result["hasBadWarning"], result)
        self.assertEqual(len(result["links"]), 1, result)
        self.assertIn("export-good", result["links"][0])


    def test_video_batch_restore_keeps_success_and_retries_only_failed_file(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{
                id: 'batch-good', title: '正常動画', hasVideo: false,
                sourceVideoKey: ''
            }];
            persist();
        }""")
        good_video = self.temp_path / "riku-video__batch-good__good.mp4"
        missing_record_video = self.temp_path / "riku-video__missing-record__lost.mp4"
        good_video.write_bytes(self.video_path.read_bytes())
        missing_record_video.write_bytes(self.video_path.read_bytes())
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#videoImportFiles").set_input_files([
            str(good_video), str(missing_record_video)
        ])
        self.wait_for_stage48_restore()
        result = page.evaluate("""async () => ({
            hasGoodVideo: state.clips[0].hasVideo,
            goodBytes: (await getClipVideo('batch-good'))?.blob?.size || 0,
            retryCount: lastVideoImportFiles.length,
            retryNames: lastVideoImportFiles.map(file => file.name),
            retryButtonVisible: getComputedStyle(document.getElementById('videoImportRetry')).display !== 'none'
        })""")
        self.assertTrue(result["hasGoodVideo"], result)
        self.assertEqual(result["goodBytes"], self.video_path.stat().st_size, result)
        self.assertEqual(result["retryCount"], 1, result)
        self.assertEqual(
            result["retryNames"], ["riku-video__missing-record__lost.mp4"], result
        )
        self.assertTrue(result["retryButtonVisible"], result)


    def test_video_integrity_scan_reports_corrupt_chunks_without_aborting_other_records(self):
        page = self.page
        result = page.evaluate("""async () => {
            await storeClipVideo('integrity-good', new Blob([
                new Uint8Array([1, 2, 3, 4])
            ], {type: 'video/mp4'}));
            await storeClipVideo('integrity-bad', new Blob([
                new Uint8Array([5, 6, 7, 8])
            ], {type: 'video/mp4'}));
            const db = await openVideoDB();
            try {
                const record = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get('integrity-bad');
                    req.onsuccess = () => resolve(req.result);
                    req.onerror = () => reject(req.error);
                });
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readwrite');
                    tx.objectStore('videoChunks').delete(
                        record.chunkPrefix + '00000000'
                    );
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
            } finally { db.close(); }
            state.clips = [
                {id: 'integrity-good', title: '正常動画', hasVideo: true},
                {id: 'integrity-bad', title: '破損動画', hasVideo: true}
            ];
            const output = document.getElementById('videoIntegrityResult');
            if (!output) return {outputMissing: true};
            await scanSavedVideoIntegrity();
            let badError = '';
            try { await getClipVideo('integrity-bad'); }
            catch (error) { badError = String(error.message || error); }
            return {
                text: output.textContent,
                goodPlayable: output.innerHTML.includes('正常動画'),
                badReported: output.textContent.includes('破損動画'),
                badError
            };
        }""")
        self.assertFalse(result.get("outputMissing"), result)
        self.assertTrue(result.get("badReported"), result)
        self.assertIn("チャンク", result["badError"])
        self.assertIn("正常動画", result["text"])


    def test_backup_restore_does_not_play_video_with_mismatched_source_identity(self):
        result = self.page.evaluate("""async () => {
            await storeClipVideo('identity-mismatch', new File([
                new Uint8Array([1, 2, 3, 4])
            ], 'old-video.mp4', {type: 'video/mp4', lastModified: 123}));
            state.clips = [{
                id: 'identity-mismatch', title: '別動画が残った記録',
                hasVideo: true,
                sourceVideoKey: 'new-video.mp4|4|456|video/mp4'
            }];
            const flagCheck = await reconcileRestoredVideoFlags(state);
            const output = document.getElementById('videoIntegrityResult');
            await scanSavedVideoIntegrity();
            return {
                text: output.textContent,
                flagCheck,
                hasVideo: state.clips[0].hasVideo,
                playableCount: Number((output.textContent.match(/再生テスト（(\\d+)本）/) || [])[1] || -1),
                storedStillExists: !!(await getClipVideo('identity-mismatch'))?.blob
            };
        }""")
        self.assertIn("識別不一致 1件", result["text"])
        self.assertIn("old-video.mp4", result["text"])
        self.assertEqual(result["playableCount"], 0, result)
        self.assertFalse(result["hasVideo"], result)
        self.assertTrue(result["flagCheck"]["ok"], result)
        self.assertTrue(result["storedStillExists"], result)


    def test_video_first_restore_can_retry_after_json_and_repeat_safely(self):
        page = self.page
        self.accept_dialogs()
        video_path = self.temp_path / "riku-video__restore-order-1__order.mp4"
        video_path.write_bytes(self.video_path.read_bytes())
        backup_path = self.temp_path / "restore-order.json"
        backup_path.write_text(json.dumps({
            "backupFormat": "riku-football-lab",
            "backupVersion": 3,
            "state": {
                "settings": {"name": "陸玖", "jersey1": 10, "jersey2": 74},
                "menus": [],
                "trainings": [],
                "measures": [],
                "clips": [{
                    "id": "restore-order-1", "title": "順序確認",
                    "hasVideo": True,
                    "sourceVideoKey": ""
                }],
                "forms": [], "matchAnalyses": [], "aiFormAnalyses": []
            }
        }, ensure_ascii=False), encoding="utf-8")

        page.locator("#videoImportFiles").set_input_files(str(video_path))
        self.wait_for_stage48_restore()
        self.assertEqual(page.evaluate("lastVideoImportFiles.length"), 1)
        self.assertEqual(page.evaluate("state.clips.length"), 0)

        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.length === 1", timeout=10000)
        self.assertIn("JSON復元後に再試行", page.locator("#videoImportRetry").inner_text())
        self.assertEqual(page.evaluate("lastVideoImportFiles.length"), 1)

        page.locator("#videoImportRetry").click()
        page.wait_for_function(
            "state.clips.length === 1 && state.clips[0].hasVideo && lastVideoImportFiles.length === 0",
            timeout=10000,
        )
        first_restore = page.evaluate("""async () => ({
            count: state.clips.length,
            bytes: (await getClipVideo('restore-order-1'))?.blob?.size || 0
        })""")
        self.assertEqual(first_restore, {"count": 1, "bytes": self.video_path.stat().st_size})

        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function(
            "state.clips.length === 1 && state.clips[0].hasVideo",
            timeout=10000,
        )
        repeated_json = page.evaluate("""async () => ({
            count: state.clips.length,
            hasVideo: state.clips[0].hasVideo,
            bytes: (await getClipVideo('restore-order-1'))?.blob?.size || 0
        })""")
        self.assertEqual(
            repeated_json, {"count": 1, "hasVideo": True, "bytes": self.video_path.stat().st_size}
        )

        page.locator("#videoImportFiles").set_input_files(str(video_path))
        self.wait_for_stage48_restore()
        repeated = page.evaluate("""async () => ({
            count: state.clips.length,
            bytes: (await getClipVideo('restore-order-1'))?.blob?.size || 0,
            retryCount: lastVideoImportFiles.length
        })""")
        self.assertEqual(repeated, {"count": 1, "bytes": 5, "retryCount": 0})


    def test_invalid_json_restore_preserves_current_state_and_storage(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{id: 'keep-existing', title: '保持する記録', hasVideo: false}];
            persist();
        }""")
        before = page.evaluate("""() => ({
            state: JSON.stringify(state),
            stored: localStorage.getItem(KEY)
        })""")
        invalid_path = self.temp_path / "invalid-restore.json"
        invalid_path.write_text('{"backupFormat":"riku-football-lab","state":', encoding="utf-8")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#importFile").set_input_files(str(invalid_path))
        page.wait_for_function("document.getElementById('importFile').value === ''", timeout=10000)
        after = page.evaluate("""() => ({
            state: JSON.stringify(state),
            stored: localStorage.getItem(KEY)
        })""")
        self.assertEqual(after, before)


    def test_json_restore_storage_failure_keeps_memory_and_reports_storage_uncertainty(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{id: 'storage-keep', title: '保存保護', hasVideo: false}];
            persist();
            window.__originalStorageSetItem = Storage.prototype.setItem;
            Storage.prototype.setItem = function(key, value) {
                if (key === KEY) throw new DOMException('quota simulated', 'QuotaExceededError');
                return window.__originalStorageSetItem.call(this, key, value);
            };
        }""")
        before = page.evaluate("() => ({state: JSON.stringify(state), stored: localStorage.getItem(KEY)})")
        backup_path = self.temp_path / "storage-failure-restore.json"
        backup_path.write_text(json.dumps({
            "settings": {"name": "別データ"},
            "trainings": [], "measures": [], "clips": [], "forms": []
        }, ensure_ascii=False), encoding="utf-8")
        messages = []
        page.on("dialog", lambda dialog: (messages.append(dialog.message), dialog.accept()))
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("document.getElementById('importFile').value === ''", timeout=10000)
        after = page.evaluate("""() => {
            Storage.prototype.setItem = window.__originalStorageSetItem;
            return {state: JSON.stringify(state), stored: localStorage.getItem(KEY)};
        }""")
        self.assertEqual(after, before)
        self.assertTrue(messages and "再読み込みせず" in messages[0], messages)


    def test_delete_clip_detaches_match_and_ai_references_without_deleting_other_records(self):
        page = self.page
        page.evaluate("""async () => {
            const key = 'clip-delete.mp4|4|123|video/mp4';
            state.clips = [{id: 'clip-delete', sourceVideoKey: key, hasVideo: true, matchAnalysisIds: ['match-keep']}];
            state.forms = [{id: 'form-keep', sourceVideoKey: 'form.mp4|4|124|video/mp4', hasVideo: false, aiAnalysisIds: ['ai-keep']}];
            state.matchAnalyses = [{id: 'match-keep', sourceVideoKey: key, clipId: 'clip-delete', videoStorageKey: 'clip-delete', aiFormAnalysisIds: ['ai-keep']}];
            state.aiFormAnalyses = [{id: 'ai-keep', sourceVideoKey: key, formId: 'form-keep', matchId: 'match-keep', matchClipId: 'clip-delete'}];
            await storeClipVideo('clip-delete', new Blob([new Uint8Array([1,2,3,4])], {type: 'video/mp4'}));
            persist();
        }""")
        page.once("dialog", lambda dialog: dialog.accept())
        page.evaluate("deleteItem('clips', 'clip-delete')")
        result = page.evaluate("""async () => ({
            clipCount: state.clips.length,
            matchClipId: state.matchAnalyses[0].clipId,
            matchVideoStorageKey: state.matchAnalyses[0].videoStorageKey,
            clipReverseIds: state.clips[0]?.matchAnalysisIds || [],
            aiMatchClipId: state.aiFormAnalyses[0].matchClipId,
            formStillExists: state.forms.some(x => x.id === 'form-keep'),
            aiFormLink: state.forms[0].aiAnalysisIds,
            videoStillExists: await getClipVideo('clip-delete')
        })""")
        self.assertEqual(result["clipCount"], 0, result)
        self.assertIsNone(result["matchClipId"], result)
        self.assertIsNone(result["matchVideoStorageKey"], result)
        self.assertEqual(result["aiMatchClipId"], None, result)
        self.assertTrue(result["formStillExists"], result)
        self.assertEqual(result["aiFormLink"], ["ai-keep"], result)
        self.assertIsNone(result["videoStillExists"], result)


    def test_delete_match_detaches_ai_links_but_preserves_form_and_training_context(self):
        page = self.page
        page.evaluate("""() => {
            state.matchAnalyses = [{id: 'match-delete', title: '削除対象', aiFormAnalysisIds: ['ai-keep']}];
            state.clips = [{id: 'clip-keep', matchAnalysisIds: ['match-delete']}];
            state.aiFormAnalyses = [{id: 'ai-keep', matchId: 'match-delete', matchTitle: '削除対象', matchDate: '2026-11-01', matchClipId: 'clip-keep'}];
            state.forms = [{id: 'form-keep', aiAnalysisIds: ['ai-keep']}];
            state.trainings = [{id: 'training-keep', linkedMatchEvents: [{matchId: 'match-delete', eventId: 'event-1'}], sourceMatch: {matchId: 'match-delete', eventId: 'event-2'}}];
            persist();
        }""")
        page.once("dialog", lambda dialog: dialog.accept())
        page.evaluate("deleteMatchScan('match-delete')")
        result = page.evaluate("""() => ({
            matchCount: state.matchAnalyses.length,
            clipLinks: state.clips[0].matchAnalysisIds,
            aiMatchId: state.aiFormAnalyses[0].matchId,
            aiMatchClipId: state.aiFormAnalyses[0].matchClipId,
            formLinks: state.forms[0].aiAnalysisIds,
            trainingLinks: state.trainings[0].linkedMatchEvents,
            trainingSourceDeleted: state.trainings[0].sourceMatch.matchRecordDeleted,
            trainingStillExists: state.trainings.length === 1
        })""")
        self.assertEqual(result["matchCount"], 0, result)
        self.assertEqual(result["clipLinks"], [], result)
        self.assertIsNone(result["aiMatchId"], result)
        self.assertIsNone(result["aiMatchClipId"], result)
        self.assertEqual(result["formLinks"], ["ai-keep"], result)
        self.assertEqual(result["trainingLinks"], [], result)
        self.assertTrue(result["trainingSourceDeleted"], result)
        self.assertTrue(result["trainingStillExists"], result)


    def test_ai_analysis_delete_rolls_back_all_links_when_persistence_fails(self):
        page = self.page
        page.evaluate("""() => {
            state.aiFormAnalyses = [{id: 'ai-delete-rollback'}];
            state.forms = [{id: 'form-rollback', aiAnalysisIds: ['ai-delete-rollback']}];
            state.matchAnalyses = [{id: 'match-rollback', aiFormAnalysisIds: ['ai-delete-rollback']}];
            persist();
            const originalSetItem = Storage.prototype.setItem;
            Storage.prototype.setItem = function(key, value) {
                if (key === 'rikuFootballLab_v3') throw new DOMException('simulated quota', 'QuotaExceededError');
                return originalSetItem.call(this, key, value);
            };
            window.__restoreStorageSetItem = () => { Storage.prototype.setItem = originalSetItem; };
        }""")
        page.once("dialog", lambda dialog: dialog.accept())
        page.evaluate("deleteAiFormAnalysis('ai-delete-rollback')")
        page.evaluate("window.__restoreStorageSetItem()")
        result = page.evaluate("""() => ({
            aiExists: state.aiFormAnalyses.some(x => x.id === 'ai-delete-rollback'),
            formLinks: state.forms[0].aiAnalysisIds,
            matchLinks: state.matchAnalyses[0].aiFormAnalysisIds
        })""")
        self.assertTrue(result["aiExists"], result)
        self.assertEqual(result["formLinks"], ["ai-delete-rollback"], result)
        self.assertEqual(result["matchLinks"], ["ai-delete-rollback"], result)


    def test_delete_ai_form_analysis_removes_reverse_links_and_keeps_source_records(self):
        page = self.page
        page.evaluate("""() => {
            state.aiFormAnalyses = [{id: 'ai-delete'}];
            state.forms = [{id: 'form-keep', aiAnalysisIds: ['ai-delete', 'ai-other']}];
            state.matchAnalyses = [{id: 'match-keep', aiFormAnalysisIds: ['ai-delete', 'ai-other']}];
            persist();
        }""")
        page.once("dialog", lambda dialog: dialog.accept())
        page.evaluate("deleteAiFormAnalysis('ai-delete')")
        result = page.evaluate("""() => ({
            aiCount: state.aiFormAnalyses.length,
            formLinks: state.forms[0].aiAnalysisIds,
            matchLinks: state.matchAnalyses[0].aiFormAnalysisIds,
            formCount: state.forms.length,
            matchCount: state.matchAnalyses.length
        })""")
        self.assertEqual(result["aiCount"], 0, result)
        self.assertEqual(result["formLinks"], ["ai-other"], result)
        self.assertEqual(result["matchLinks"], ["ai-other"], result)
        self.assertEqual(result["formCount"], 1, result)
        self.assertEqual(result["matchCount"], 1, result)


    def test_restored_analysis_links_require_unique_identity_and_are_idempotent(self):
        result = self.page.evaluate("""() => {
            const key = 'same-source.mp4|5|123|video/mp4';
            const restored = {
                clips: [
                    {id: 'clip-a', sourceVideoKey: key, matchAnalysisIds: []},
                    {id: 'clip-b', sourceVideoKey: key, matchAnalysisIds: []}
                ],
                forms: [
                    {id: 'form-a', sourceVideoKey: key, hasVideo: true, aiAnalysisIds: []},
                    {id: 'form-b', sourceVideoKey: key, hasVideo: true, aiAnalysisIds: []}
                ],
                matchAnalyses: [
                    {id: 'match-ambiguous', sourceVideoKey: key, aiFormAnalysisIds: []},
                    {id: 'match-explicit', clipId: 'clip-b', sourceVideoKey: key, aiFormAnalysisIds: []}
                ],
                aiFormAnalyses: [
                    {id: 'ai-ambiguous', sourceVideoKey: key},
                    {id: 'ai-explicit', sourceVideoKey: key, formId: 'form-b', matchId: 'match-explicit'}
                ]
            };
            reconcileRestoredAnalysisLinks(restored);
            reconcileRestoredAnalysisLinks(restored);
            return {
                ambiguous: restored.aiFormAnalyses[0],
                explicit: restored.aiFormAnalyses[1],
                ambiguousMatchClip: restored.matchAnalyses[0].clipId || null,
                explicitMatchClip: restored.matchAnalyses[1].clipId,
                clipAIds: restored.clips[0].matchAnalysisIds,
                clipBIds: restored.clips[1].matchAnalysisIds,
                formAIds: restored.forms[0].aiAnalysisIds,
                formBIds: restored.forms[1].aiAnalysisIds,
                matchIds: restored.matchAnalyses[1].aiFormAnalysisIds
            };
        }""")
        self.assertIsNone(result["ambiguous"].get("formId"), result)
        self.assertIsNone(result["ambiguous"].get("matchId"), result)
        self.assertIsNone(result["ambiguousMatchClip"], result)
        self.assertEqual(result["explicit"]["formId"], "form-b", result)
        self.assertEqual(result["explicit"]["matchId"], "match-explicit", result)
        self.assertEqual(result["explicitMatchClip"], "clip-b", result)
        self.assertEqual(result["clipAIds"], [], result)
        self.assertEqual(result["clipBIds"], ["match-explicit"], result)
        self.assertEqual(result["formAIds"], [], result)
        self.assertEqual(result["formBIds"], ["ai-explicit"], result)
        self.assertEqual(result["matchIds"], ["ai-explicit"], result)


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
        original_source_key = page.evaluate("state.matchAnalyses[0].sourceVideoKey")
        self.assertTrue(original_source_key)
        # Simulate Safari page reload: the file input and pendingMatchSave promise are gone,
        # but the original video and its metadata remain in IndexedDB.
        page.reload(wait_until="load")
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("同一動画の端末保存")
        page.evaluate("saveClip()")
        page.wait_for_function("state.clips.length === 1 && state.clips[0].hasVideo")
        linked = page.evaluate("""() => ({
            clipId: String(state.clips[0].id),
            matchId: String(state.matchAnalyses[0].id),
            matchClipId: String(state.matchAnalyses[0].clipId),
            storageKey: state.matchAnalyses[0].videoStorageKey,
            matchIds: state.clips[0].matchAnalysisIds.map(String),
            clipSourceVideoKey: state.clips[0].sourceVideoKey,
            matchSourceVideoKey: state.matchAnalyses[0].sourceVideoKey,
            savedVideoName: state.clips[0].title
        })""")
        self.assertEqual(linked["matchClipId"], linked["clipId"], linked)
        self.assertEqual(linked["storageKey"], linked["clipId"], linked)
        self.assertIn(linked["matchId"], linked["matchIds"], linked)
        self.assertEqual(linked["clipSourceVideoKey"], original_source_key, linked)
        self.assertEqual(linked["matchSourceVideoKey"], original_source_key, linked)
        self.assertEqual(linked["savedVideoName"], "同一動画の端末保存", linked)
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
        self.assertIn("削除を取り消しました", result["alert"])


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
            const uploadSizes = {};
            let completed = 0;
            let activeUploadId = '';
            window.fetch = async (url, options = {}) => {
                const path = new URL(url).pathname;
                if (path === '/analyze/match/uploads' && options.method === 'POST') {
                    const payload = JSON.parse(options.body);
                    initPayloads.push(payload);
                    activeUploadId = 'synthetic-' + initPayloads.length;
                    uploadSizes[activeUploadId] = payload.size_bytes;
                    return new Response(JSON.stringify({
                        ok: true, upload_id: activeUploadId, chunk_size: 6 * 1024 * 1024,
                        total_chunks: Math.ceil(payload.size_bytes / (6 * 1024 * 1024))
                    }), {status: 201, headers: {'Content-Type': 'application/json'}});
                }
                const chunk = path.match(/\/analyze\/match\/uploads\/(synthetic-\d+)\/(\d+)$/);
                if (chunk && options.method === 'PUT') {
                    const part = options.body.get('file');
                    received.push({upload: chunk[1], index: Number(chunk[2]), size: part.size});
                    return new Response(JSON.stringify({
                        ok: true, chunk_index: Number(chunk[2]),
                        received_bytes: Math.min(uploadSizes[chunk[1]], (Number(chunk[2]) + 1) * (6 * 1024 * 1024)),
                        total_bytes: uploadSizes[chunk[1]]
                    }), {status: 200, headers: {'Content-Type': 'application/json'}});
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
                counters["total_bytes"] = request.post_data_json["size_bytes"]
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True, "upload_id": "mock-upload",
                                               "chunk_size": 6 * 1024 * 1024,
                                               "total_chunks": request.post_data_json["size_bytes"] // (6 * 1024 * 1024) +
                                               (1 if request.post_data_json["size_bytes"] % (6 * 1024 * 1024) else 0)}))
            elif path.startswith("/analyze/match/uploads/mock-upload/") and request.method == "PUT":
                counters["chunks"] += 1
                index = int(path.rsplit("/", 1)[-1])
                received_bytes = min(counters["total_bytes"], (index + 1) * 6 * 1024 * 1024)
                route.fulfill(status=200, headers=headers, content_type="application/json",
                              body=json.dumps({"ok": True, "chunk_index": index,
                                               "received_bytes": received_bytes,
                                               "total_bytes": counters["total_bytes"]}))
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
                                                   "performance_metrics": {
                                                       "conversion_seconds": 0.12,
                                                       "pose_scan_seconds": 12.34,
                                                       "candidate_and_clip_seconds": 2.5,
                                                       "total_processing_seconds": 15.0,
                                                       "sampled_frames": 1829,
                                                       "pose_scan_breakdown": {
                                                           "pose_inference_seconds": 434.85,
                                                           "landmark_postprocess_seconds": 83.02
                                                       },
                                                       "pose_inference_sample_count": 1829,
                                                       "pose_inference_p50_seconds": 0.2314,
                                                       "pose_inference_p95_seconds": 0.4123,
                                                       "pose_inference_max_seconds": 0.6891
                                                   }
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
            displayed = page.locator("#matchAiResult").inner_text()
            for expected in ("測定 1829件", "中央値 0.2314秒", "95%点 0.4123秒", "最大 0.6891秒"):
                self.assertIn(expected, displayed, displayed)
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


    def test_completed_match_job_restores_and_saves_result_once_after_reload(self):
        page = self.page
        self.accept_dialogs()
        api_base = "https://restore-match-job-mock.invalid"
        page.route(api_base + "/**", lambda route: route.fulfill(
            status=200,
            headers={"Access-Control-Allow-Origin": "*"},
            content_type="application/json",
            body=json.dumps(
                {"ok": True} if route.request.url.endswith("/health") else {
                    "status": "completed", "progress": 100, "stage": "完了",
                    "result": {
                        "job_id": "restore-job-123",
                        "requested_jersey_numbers": "10,74",
                        "summary": {
                            "duration_seconds": 1200, "sampled_pose_frames": 0,
                            "frames": [], "candidate_events": [], "feedback": [],
                            "person_detection_summary": {}, "person_track_summary": {},
                            "jersey_ocr_summary": {}
                        }
                    }
                },
            ),
        ))
        metadata = page.evaluate("""async (apiBase) => {
            state.matchAnalyses = [];
            state.settings.apiBaseUrl = apiBase;
            persist();
            const source = new File([new Uint8Array([1, 2, 3, 4])], 'twenty-minute-match.mp4', {
                type: 'video/mp4', lastModified: 1700000000123
            });
            const sourceKey = getVideoSourceKey(source);
            await savePendingMatchJob({
                jobId: 'restore-job-123', apiBaseUrl: apiBase, sourceKey,
                filename: source.name, sizeBytes: source.size, createdAt: 1700000000
            });
            return {sourceKey, filename: source.name};
        }""", api_base)
        page.reload(wait_until="load")
        page.wait_for_function(
            "() => document.getElementById('matchAiResult').textContent.includes('全編スキャンが完了しました')",
            timeout=20000,
        )
        self.assertIn("このAI解析結果を履歴に保存", page.locator("#matchAiResult").inner_text())
        # A local persistence failure must not discard the only recoverable job pointer.
        page.evaluate("""() => {
            window.__originalMatchPersist = window.persist;
            window.persist = () => false;
        }""")
        page.get_by_role("button", name="このAI解析結果を履歴に保存").click()
        failed_save = page.evaluate("""async () => ({
            count: state.matchAnalyses.length,
            savedId: document.getElementById('matchAiResult').dataset.savedId || null,
            pending: await getPendingMatchJob()
        })""")
        self.assertEqual(failed_save["count"], 0, failed_save)
        self.assertIsNone(failed_save["savedId"], failed_save)
        self.assertEqual(failed_save["pending"]["jobId"], "restore-job-123", failed_save)
        page.evaluate("""() => {
            window.persist = window.__originalMatchPersist;
            delete window.__originalMatchPersist;
        }""")
        page.get_by_role("button", name="このAI解析結果を履歴に保存").click()
        saved = page.evaluate("""async () => ({
            count: state.matchAnalyses.length,
            record: state.matchAnalyses[0],
            pending: await getPendingMatchJob(),
            historyText: document.getElementById('matchScanRecords').innerText
        })""")
        self.assertEqual(saved["count"], 1, saved)
        self.assertEqual(saved["savedId"], str(saved["record"]["id"]), saved)
        self.assertEqual(saved["record"]["jobId"], "restore-job-123", saved)
        self.assertEqual(saved["record"]["sourceVideoKey"], metadata["sourceKey"], saved)
        self.assertEqual(saved["record"]["title"], metadata["filename"], saved)
        self.assertIsNone(saved["pending"], saved)
        self.assertIn(metadata["filename"], saved["historyText"])
        page.evaluate("() => saveMatchScanResult()")
        self.assertEqual(page.evaluate("state.matchAnalyses.length"), 1)


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
                "buffer": b"\xab" * (6 * 1024 * 1024 + 23),
            })
            page.wait_for_function("() => document.getElementById('videoFile').files.length === 1")
            original = page.evaluate("""async () => {
                const file = document.getElementById('videoFile').files[0];
                await storeClipVideo('__pending_match_video__', file);
                const contentFingerprint = await getVideoContentFingerprint(file);
                await savePendingMatchUpload({sourceKey:getVideoSourceKey(file),contentFingerprint,size:file.size,
                    name:file.name,lastModified:file.lastModified,jerseyNumbers:'10,74',
                    uploadId:'resume-upload',chunkSize:12*1024*1024,totalChunks:1,nextChunk:1,createdAt:Date.now()});
                return {size:file.size,sourceKey:getVideoSourceKey(file),contentFingerprint};
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
                                                   "next_chunk":1,"chunk_size":6*1024*1024,"total_chunks":2,
                                                   "received_bytes":6*1024*1024,
                                                   "total_bytes":original["size"],"complete":False}))
                elif path == "/analyze/match/uploads/resume-upload/1" and request.method == "PUT":
                    counters["puts"].append(1)
                    counters["putMarkerBytes"] = (request.post_data_buffer or b"").count(b"\xab")
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"chunk_index":1,
                                                    "received_bytes":original["size"],"total_bytes":original["size"]}))
                elif path == "/analyze/match/uploads/resume-upload/complete" and request.method == "POST":
                    counters["completed"] += 1
                    route.fulfill(status=202, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"job_id":"resume-job","status":"queued"}))
                else:
                    route.fulfill(status=404, headers=headers, content_type="application/json",
                                  body=json.dumps({"detail":"unexpected request: "+path}))
            page.route("**/*", mock_api)
            result = page.evaluate("""async () => {
                const originalFetch = window.fetch.bind(window);
                window.__resumePutPartSizes = [];
                window.fetch = async (url, options = {}) => {
                    if (String(url).endsWith('/uploads/resume-upload/1') && options.method === 'PUT') {
                        const part = options.body instanceof FormData ? options.body.get('file') : null;
                        window.__resumePutPartSizes.push(part?.size || 0);
                    }
                    return originalFetch(url, options);
                };
                const stored = await getClipVideo('__pending_match_video__');
                if (!stored || !(stored.blob instanceof Blob)) throw new Error('saved source video missing after reload');
                const file = new File([stored.blob], stored.name, {type:stored.type, lastModified:stored.lastModified});
                const response = await uploadMatchVideoInChunks(file, '10,74', document.getElementById('matchAiResult'));
                return {jobId:response.job_id,size:file.size,pending:await getPendingMatchUpload(),putPartSizes:window.__resumePutPartSizes};
            }""")
            self.assertEqual(result["jobId"], "resume-job", result)
            self.assertEqual(result["size"], original["size"], result)
            self.assertIsNone(result["pending"], result)
            self.assertEqual(counters, {"status":1,"created":0,"puts":[1],"completed":1})
            self.assertEqual(result["putPartSizes"], [23], result)
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
                    counters["size"] = request.post_data_json["size_bytes"]
                    counters["chunk_size"] = 6 * 1024 * 1024
                    route.fulfill(status=201, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "upload_id": "webkit-upload",
                                                   "chunk_size": counters["chunk_size"],
                                                   "total_chunks": (counters["size"] + counters["chunk_size"] - 1) // counters["chunk_size"]}))
                elif path.startswith("/analyze/match/uploads/webkit-upload/") and request.method == "PUT":
                    counters["chunks"] += 1
                    index = int(path.rsplit("/", 1)[-1])
                    received_bytes = min(counters["size"], (index + 1) * counters["chunk_size"])
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "chunk_index": index,
                                                   "received_bytes": received_bytes,
                                                   "total_bytes": counters["size"]}))
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





    def test_match_scan_history_restores_performance_and_candidate_clip_metadata(self):
        page = self.page
        page.route("**/__playback_fixture__.webm", lambda route: route.fulfill(status=200, content_type="video/webm", body=self.video_path.read_bytes()))
        page.evaluate("""() => { state.settings.apiBaseUrl = window.location.origin; persist(); }""")
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("実動画履歴復元メタデータ")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.evaluate("""() => {
            window.alert = () => {};
            const result = {
                requested_jersey_numbers: "10,74",
                summary: {
                    duration_seconds: 914.33, sampled_pose_frames: 1829,
                    sampling_interval_seconds: 0.5, sampling_rate_fps: 2,
                    video_scan_quality: {status: "usable_for_review", sampled_video_frames: 1829, detected_pose_frames: 1384, detection_rate: 76},
                    scan_timing: {pose_inference_seconds: 470.73, pose_inference_sample_count: 1829, pose_inference_p50_seconds: 0.21, pose_inference_p95_seconds: 0.4, pose_inference_max_seconds: 0.7},
                    performance_metrics: {pose_scan_seconds: 802.67, candidate_and_clip_seconds: 68.8, total_processing_seconds: 871.84},
                    person_detection_summary: {average_people_per_sample: 1.05, max_people_in_one_frame: 4},
                    person_track_summary: {provisional_tracks: 125},
                    jersey_ocr_summary: {candidate_detection_counts: {}},
                    candidate_events: Array.from({length: 8}, (_, i) => ({id: "scene-" + (i + 1), time_seconds: 14 + i * 60, label: "動きの変化", clip_available: true, clip_url: "/analyze/jobs/job-test/clips/scene-" + (i + 1), dense_analysis: {sampled_frames: 15}}))
                }
            };
            document.getElementById("matchAiResult").dataset.result = JSON.stringify(result);
            return saveMatchScanResult();
        }""")
        saved = page.evaluate("""() => {
            const m = state.matchAnalyses[0];
            return {
                samplingRate: m.samplingRate,
                scanTiming: m.scanTiming,
                performanceMetrics: m.performanceMetrics,
                personDetection: m.personDetection,
                personTrackSummary: m.personTrackSummary,
                jerseyOcrSummary: m.jerseyOcrSummary,
                candidateCount: m.candidateEvents.length,
                candidates: m.candidateEvents.map(ev => ({id: ev.id, clipUrl: ev.clipUrl, clipAvailable: ev.clipAvailable}))
            };
        }""")
        self.assertEqual(saved["samplingRate"], 2)
        self.assertEqual(saved["scanTiming"]["pose_inference_sample_count"], 1829)
        self.assertEqual(saved["scanTiming"]["pose_inference_p95_seconds"], 0.4)
        self.assertEqual(saved["performanceMetrics"]["total_processing_seconds"], 871.84)
        self.assertEqual(saved["personDetection"]["max_people_in_one_frame"], 4)
        self.assertEqual(saved["personTrackSummary"]["provisional_tracks"], 125)
        self.assertEqual(saved["candidateCount"], 8)
        self.assertEqual([x["clipUrl"] for x in saved["candidates"]], [f"/analyze/jobs/job-test/clips/scene-{i}" for i in range(1, 9)])
        self.assertTrue(all(x["clipAvailable"] for x in saved["candidates"]))
        page.reload()
        page.evaluate("renderAll()")
        page.locator('.nav button[data-view="video"]').click()
        restored = page.evaluate("""() => {
            const m = state.matchAnalyses[0];
            return {metrics: m.performanceMetrics, scan: m.scanTiming, candidates: m.candidateEvents.map(ev => ({id: ev.id, clipUrl: ev.clipUrl, clipAvailable: ev.clipAvailable}))};
        }""")
        self.assertEqual(restored["metrics"]["total_processing_seconds"], 871.84)
        self.assertEqual(restored["scan"]["pose_inference_p95_seconds"], 0.4)
        self.assertEqual(len(restored["candidates"]), 8)
        self.assertEqual([x["clipUrl"] for x in restored["candidates"]], [f"/analyze/jobs/job-test/clips/scene-{i}" for i in range(1, 9)])
        self.assertTrue(all(x["clipAvailable"] for x in restored["candidates"]))
        saved_id = page.evaluate("state.matchAnalyses[0].id")
        detail = page.locator(f"#match-scan-detail-{saved_id}")
        self.assertEqual(detail.count(), 1, page.locator("body").inner_text()[-3000:])
        detail.evaluate("(el) => { el.hidden = false; }")
        clips = detail.locator("video")
        self.assertEqual(clips.count(), 8)
        for index in range(8):
            clip = clips.nth(index)
            source = clip.get_attribute("src") or ""
            self.assertTrue(source.endswith(f"/scene-{index + 1}"), source)
            self.assertIsNotNone(clip.get_attribute("controls"))
        playable = clips.nth(0)
        playable.evaluate("(el) => { el.src = '/__playback_fixture__.webm'; el.preload = 'auto'; el.load(); }")
        page.wait_for_function("() => { const el = document.querySelector('#match-scan-detail-" + str(saved_id) + " video'); return !!el && el.readyState >= 1; }", timeout=10000)
        playback = playable.evaluate("(el) => el.play().then(() => ({paused: el.paused, readyState: el.readyState}))")
        self.assertFalse(playback["paused"])
        self.assertGreaterEqual(playback["readyState"], 2)

    def test_record_link_integrity_rebuilds_only_deterministic_reverse_links(self):
        page = self.page
        result = page.evaluate("""() => {
            const data = {
                clips: [{id:'clip-a', matchAnalysisIds:['missing-match','match-bad']}],
                forms: [{id:'form-a', aiAnalysisIds:['ai-a','missing-ai']}],
                matchAnalyses: [{id:'match-bad', clipId:'clip-b', aiFormAnalysisIds:['missing-ai']}],
                aiFormAnalyses: [{id:'ai-a', formId:'form-a', matchId:'missing-match', matchClipId:'clip-gone'}]
            };
            const report = reconcileRecordReverseLinks(data);
            const again = reconcileRecordReverseLinks(data);
            return {data, report, again};
        }""")
        self.assertEqual(result["data"]["clips"][0]["matchAnalysisIds"], [])
        self.assertEqual(result["data"]["forms"][0]["aiAnalysisIds"], ["ai-a"])
        self.assertEqual(result["data"]["matchAnalyses"][0]["aiFormAnalysisIds"], [])
        self.assertTrue(any("matchId" in x for x in result["report"]["danglingForward"]))
        self.assertTrue(any("matchClipId" in x for x in result["report"]["danglingForward"]))
        self.assertEqual(result["again"]["repaired"], [])

    def test_record_link_integrity_keeps_forward_references_and_does_not_delete_video_data(self):
        page = self.page
        result = page.evaluate("""async () => {
            state.clips = [{id:'orphan-clip', hasVideo:false, matchAnalysisIds:[]}];
            state.forms = [];
            state.matchAnalyses = [{id:'match-orphan-ref', clipId:'missing-clip', aiFormAnalysisIds:[]}];
            state.aiFormAnalyses = [{id:'ai-orphan-ref', formId:'missing-form', matchId:'missing-match'}];
            await storeClipVideo('video-without-record', new Blob([new Uint8Array([1,2,3])], {type:'video/mp4'}));
            const before = await getClipVideo('video-without-record');
            const links = reconcileRecordReverseLinks(state);
            const after = await getClipVideo('video-without-record');
            return {links, videoSize:after.blob.size, matchClipId:state.matchAnalyses[0].clipId, formId:state.aiFormAnalyses[0].formId};
        }""")
        self.assertEqual(result["videoSize"], 3)
        self.assertEqual(result["matchClipId"], "missing-clip")
        self.assertEqual(result["formId"], "missing-form")

    def test_record_link_integrity_repair_rolls_back_when_persistence_fails(self):
        page = self.page
        result = page.evaluate("""async () => {
            state.clips = [{id:'clip-rollback', matchAnalysisIds:['stale-id']}];
            state.forms = [];
            state.matchAnalyses = [];
            state.aiFormAnalyses = [];
            const before = JSON.stringify(state.clips);
            const original = Storage.prototype.setItem;
            Storage.prototype.setItem = function(key, value) {
                if (key === KEY) throw new DOMException('quota', 'QuotaExceededError');
                return original.call(this, key, value);
            };
            try { await scanAndRepairRecordIntegrity(); }
            finally { Storage.prototype.setItem = original; }
            return {before, after:JSON.stringify(state.clips), message:document.getElementById('videoIntegrityResult').textContent};
        }""")
        self.assertEqual(result["after"], result["before"])
        self.assertIn("保存に失敗", result["message"])

    def test_integrity_scan_reports_orphan_video_and_chunk_without_deleting_them(self):
        page = self.page
        result = page.evaluate("""async () => {
            state.clips = [];
            state.forms = [];
            state.matchAnalyses = [];
            state.aiFormAnalyses = [];
            await storeClipVideo('video-no-record', new Blob([new Uint8Array([1,2,3])], {type:'video/mp4'}));
            const db = await openVideoDB();
            try {
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readwrite');
                    tx.objectStore('videoChunks').put(new Uint8Array([9,9]), 'missing-owner|old-generation|00000000');
                    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
                });
            } finally { db.close(); }
            await scanAndRepairRecordIntegrity();
            const video = await getClipVideo('video-no-record');
            const checkDb = await openVideoDB();
            let chunkExists = false;
            try {
                chunkExists = await new Promise((resolve, reject) => {
                    const tx = checkDb.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get('missing-owner|old-generation|00000000');
                    req.onsuccess = () => resolve(!!req.result); req.onerror = () => reject(req.error);
                });
            } finally { checkDb.close(); }
            return {message:document.getElementById('videoIntegrityResult').textContent,videoSize:video.blob.size,chunkExists};
        }""")
        self.assertIn("記録なし動画 1件", result["message"])
        self.assertIn("所有動画なしチャンク 1件", result["message"])
        self.assertEqual(result["videoSize"], 3)
        self.assertTrue(result["chunkExists"])

    def test_duplicate_record_ids_and_ambiguous_targets_are_never_auto_repaired(self):
        result = self.page.evaluate("""() => {
            const data = {
                clips: [{id:'dup-clip', matchAnalysisIds:['keep-me']}, {id:'dup-clip', matchAnalysisIds:['keep-me-too']}],
                forms: [],
                matchAnalyses: [{id:'match-a', clipId:'dup-clip', aiFormAnalysisIds:[]}],
                aiFormAnalyses: []
            };
            const report = reconcileRecordReverseLinks(data);
            return {data, report};
        }""")
        self.assertIn("clips:dup-clip", result["report"]["duplicateIds"])
        self.assertTrue(any("dup-clip" in item for item in result["report"]["ambiguousReferences"]))
        self.assertEqual(result["data"]["clips"][0]["matchAnalysisIds"], ["keep-me"])
        self.assertEqual(result["data"]["clips"][1]["matchAnalysisIds"], ["keep-me-too"])

    def test_restore_link_reconciliation_does_not_guess_between_duplicate_or_multiple_candidates(self):
        result = self.page.evaluate("""() => {
            const restored = {
                clips: [{id:'clip-a', sourceVideoKey:'same-source', matchAnalysisIds:[]}, {id:'clip-b', sourceVideoKey:'same-source', matchAnalysisIds:[]}],
                forms: [],
                matchAnalyses: [{id:'match-a', sourceVideoKey:'same-source'}],
                analyses: []
            };
            const links = reconcileRestoredAnalysisLinks(restored);
            const duplicateIdRestore = reconcileRestoredAnalysisLinks({
                clips: [{id:'same-id', sourceVideoKey:'one', matchAnalysisIds:[]}, {id:'same-id', sourceVideoKey:'one', matchAnalysisIds:[]}],
                forms: [], matchAnalyses: [{id:'match-b', clipId:'same-id', sourceVideoKey:'one'}], aiFormAnalyses:[]
            });
            return {links, duplicateIdRestore};
        }""")
        self.assertIsNone(result["links"]["matches"][0].get("clipId"))
        self.assertEqual(result["links"]["clips"][0]["matchAnalysisIds"], [])
        self.assertIsNone(result["duplicateIdRestore"]["matches"][0].get("clipId"))

    def test_integrity_scan_flags_full_video_identity_mismatch_without_relinking(self):
        result = self.page.evaluate("""async () => {
            const file = new File([new Uint8Array([1,2,3,4])], 'actual.mp4', {type:'video/mp4', lastModified:1234});
            state.clips = [{id:'identity-clip', hasVideo:true, sourceVideoKey:getVideoSourceKey(new File([new Uint8Array([1,2,3,4])], 'expected.mp4', {type:'video/mp4', lastModified:1234})), matchAnalysisIds:[]}];
            state.forms = []; state.matchAnalyses = []; state.aiFormAnalyses = [];
            await storeClipVideo('identity-clip', file);
            await scanAndRepairRecordIntegrity();
            return {message:document.getElementById('videoIntegrityResult').textContent,source:state.clips[0].sourceVideoKey};
        }""")
        self.assertIn("動画識別情報不一致 1件", result["message"])
        self.assertIn("保留・動画識別情報不一致", result["message"])
        self.assertIn("expected.mp4", result["source"])

    def test_backup_restore_repeated_twice_is_idempotent_for_record_ids_and_links(self):
        import json
        backup = {
            "backupFormat": "riku-football-lab",
            "backupVersion": 3,
            "videoFilesIncluded": False,
            "state": {
                "settings": {"name": "陸玖"},
                "menus": [],
                "trainings": [],
                "measures": [],
                "clips": [{"id": "repeat-clip", "sourceVideoKey": "same.mp4|4|123|video/mp4", "hasVideo": False, "matchAnalysisIds": []}],
                "forms": [{"id": "repeat-form", "sourceVideoKey": "form.mp4|4|123|video/mp4", "hasVideo": False, "aiAnalysisIds": []}],
                "matchAnalyses": [{"id": "repeat-match", "sourceVideoKey": "same.mp4|4|123|video/mp4", "aiFormAnalysisIds": []}],
                "aiFormAnalyses": [{"id": "repeat-ai", "sourceVideoKey": "form.mp4|4|123|video/mp4", "formId": "repeat-form"}]
            }
        }
        backup_path = self.temp_path / "repeat-backup.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        for _ in range(2):
            self.page.once("dialog", lambda dialog: dialog.accept())
            self.page.locator("#importFile").set_input_files(str(backup_path))
            self.page.wait_for_function("state.clips.length === 1 && state.forms.length === 1 && state.matchAnalyses.length === 1 && state.aiFormAnalyses.length === 1")
        result = self.page.evaluate("""() => ({
            clipIds: state.clips.map(x => x.id),
            formIds: state.forms.map(x => x.id),
            matchIds: state.matchAnalyses.map(x => x.id),
            aiIds: state.aiFormAnalyses.map(x => x.id),
            clipReverse: state.clips[0].matchAnalysisIds,
            formReverse: state.forms[0].aiAnalysisIds
        })""")
        self.assertEqual(result["clipIds"], ["repeat-clip"])
        self.assertEqual(result["formIds"], ["repeat-form"])
        self.assertEqual(result["matchIds"], ["repeat-match"])
        self.assertEqual(result["aiIds"], ["repeat-ai"])
        self.assertEqual(result["clipReverse"], ["repeat-match"])
        self.assertEqual(result["formReverse"], ["repeat-ai"])

    def test_live_source_key_linking_stops_when_multiple_records_match(self):
        result = self.page.evaluate("""() => {
            const key = 'shared.mp4|4|123|video/mp4';
            state.clips = [
                {id:'clip-one', sourceVideoKey:key, matchAnalysisIds:[]},
                {id:'clip-two', sourceVideoKey:key, matchAnalysisIds:[]}
            ];
            state.matchAnalyses = [{id:'match-one', sourceVideoKey:key}];
            state.forms = [{id:'form-one', sourceVideoKey:key, aiAnalysisIds:[]}];
            state.aiFormAnalyses = [
                {id:'ai-one', sourceVideoKey:key},
                {id:'ai-two', sourceVideoKey:key}
            ];
            const clipLinks = syncVideoClipAnalysisLinks(state.clips[0]);
            const formLinks = syncAiFormAnalysisLinks(state.forms[0]);
            const matchLinks = syncAiFormAnalysisMatchLinks(state.aiFormAnalyses[0]);
            return {clipLinks:clipLinks.length,formLinks:formLinks.length,matchLinks:matchLinks.length,matchClipId:state.matchAnalyses[0].clipId||null,formIds:state.aiFormAnalyses.map(x=>x.formId||null)};
        }""")
        self.assertEqual(result["clipLinks"], 0)
        self.assertEqual(result["formLinks"], 0)
        self.assertEqual(result["matchLinks"], 0)
        self.assertIsNone(result["matchClipId"])
        self.assertEqual(result["formIds"], [None, None])

    def test_restored_video_identity_checks_name_size_and_type_but_not_download_timestamp(self):
        result = self.page.evaluate("""() => ({
            valid: validateRestoredVideoIdentity('goal.mp4|4|123|video%2Fmp4', 'goal.mp4', 4, 'video/mp4'),
            wrongName: validateRestoredVideoIdentity('goal.mp4|4|123|video%2Fmp4', 'other.mp4', 4, 'video/mp4'),
            wrongSize: validateRestoredVideoIdentity('goal.mp4|4|123|video%2Fmp4', 'goal.mp4', 5, 'video/mp4'),
            wrongType: validateRestoredVideoIdentity('goal.mp4|4|123|video%2Fmp4', 'goal.mp4', 4, 'video/quicktime')
        })""")
        self.assertTrue(result["valid"]["ok"], result)
        self.assertFalse(result["wrongName"]["ok"], result)
        self.assertFalse(result["wrongSize"]["ok"], result)
        self.assertFalse(result["wrongType"]["ok"], result)

    def test_backup_snapshot_is_stable_when_live_state_changes_after_capture(self):
        result = self.page.evaluate("""() => {
            const current = {clips:[{id:'before'}], matchAnalyses:[]};
            const snapshot = createBackupStateSnapshot(current);
            current.clips.push({id:'after'});
            return {snapshotIds:snapshot.clips.map(x=>x.id),liveIds:current.clips.map(x=>x.id)};
        }""")
        self.assertEqual(result["snapshotIds"], ["before"])
        self.assertEqual(result["liveIds"], ["before", "after"])

    def test_reimporting_same_video_backup_twice_skips_without_duplicate_storage(self):
        page = self.page
        page.evaluate("""() => {
            state.clips = [{id:'repeat-video', title:'同一動画', hasVideo:false}];
            state.forms = []; persist();
        }""")
        video = self.temp_path / "riku-video__repeat-video__repeat.mp4"
        video.write_bytes(self.video_path.read_bytes())
        for _ in range(2):
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#videoImportFiles").set_input_files(str(video))
            self.wait_for_stage48_restore()
        result = page.evaluate("""async () => {
            const stored = await getClipVideo('repeat-video');
            const db = await openVideoDB();
            try {
                const count = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').count();
                    req.onsuccess = () => resolve(req.result);
                    req.onerror = () => reject(req.error);
                });
                return {hasVideo:state.clips[0].hasVideo, size:stored?.blob?.size || 0, count};
            } finally { db.close(); }
        }""")
        self.assertTrue(result["hasVideo"], result)
        self.assertEqual(result["size"], self.video_path.stat().st_size, result)
        self.assertEqual(result["count"], 1, result)

    def test_backup_diagnostics_report_duplicate_video_keys_and_dangling_links_read_only(self):
        result = self.page.evaluate("""() => {
            const data = {
                clips: [
                    {id:'clip-a', sourceVideoKey:'same.mp4|4|1|video/mp4', matchAnalysisIds:['missing-match']},
                    {id:'clip-b', sourceVideoKey:'same.mp4|4|1|video/mp4', matchAnalysisIds:[]}
                ],
                forms: [], matchAnalyses: [], aiFormAnalyses: []
            };
            const before = JSON.stringify(data);
            const diagnostics = getBackupIdentityDiagnostics(data);
            return {before, after:JSON.stringify(data), diagnostics};
        }""")
        self.assertEqual(result["before"], result["after"])
        self.assertEqual(len(result["diagnostics"]["duplicateSourceKeys"]), 1)
        self.assertTrue(result["diagnostics"]["staleReverse"])
        self.assertEqual(result["diagnostics"]["danglingForward"], [])

    def test_integrity_scan_does_not_flag_download_timestamp_changes(self):
        result = self.page.evaluate("""async () => {
            const original = new File([new Uint8Array([1,2,3,4])], 'restored.mp4', {type:'video/mp4', lastModified:123});
            const downloaded = new File([new Uint8Array([1,2,3,4])], 'restored.mp4', {type:'video/mp4', lastModified:999999});
            state.clips = [{id:'timestamp-clip', hasVideo:true, sourceVideoKey:getVideoSourceKey(original), matchAnalysisIds:[]}];
            state.forms=[];state.matchAnalyses=[];state.aiFormAnalyses=[];
            await storeClipVideo('timestamp-clip', downloaded);
            await scanAndRepairRecordIntegrity();
            return document.getElementById('videoIntegrityResult').textContent;
        }""")
        self.assertIn("動画識別情報不一致 0件", result)

    def test_backup_restore_reload_relinks_and_plays_match_and_form_videos(self):
        page = self.page
        self.accept_dialogs()
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.locator("#formFile").set_input_files(str(self.video_path))
        metadata = page.evaluate("""async () => {
            const matchFile = document.getElementById('videoFile').files[0];
            const formFile = document.getElementById('formFile').files[0];
            const matchKey = getVideoSourceKey(matchFile);
            const formKey = getVideoSourceKey(formFile);
            await storeClipVideo('restore-play-clip', matchFile);
            await storeClipVideo('form-restore-play', formFile);
            return {matchKey, formKey, matchName:matchFile.name, formName:formFile.name};
        }""")
        import json
        backup = {
            "backupFormat": "riku-football-lab", "backupVersion": 3,
            "videoFilesIncluded": False,
            "state": {
                "settings": {"name": "陸玖", "jersey1": 10, "jersey2": 74, "apiBaseUrl": ""},
                "menus": [], "trainings": [], "measures": [],
                "clips": [{
                    "id": "restore-play-clip", "title": "復元した試合動画",
                    "date": "2026-11-15", "hasVideo": True,
                    "sourceVideoKey": metadata["matchKey"], "matchAnalysisIds": []
                }],
                "forms": [{
                    "id": "form-restore-play", "title": "復元したフォーム動画",
                    "date": "2026-11-15", "hasVideo": True,
                    "sourceVideoKey": metadata["formKey"], "aiAnalysisIds": []
                }],
                "matchAnalyses": [{
                    "id": "restore-play-match", "title": "復元試合分析",
                    "date": "2026-11-15", "sourceVideoKey": metadata["matchKey"],
                    "candidateEvents": [{"id": "restore-event", "time": 0, "label": "復元場面"}],
                    "aiFormAnalysisIds": []
                }],
                "aiFormAnalyses": [{
                    "id": "restore-play-ai", "title": "復元フォームAI分析",
                    "date": "2026-11-15", "sourceVideoKey": metadata["formKey"],
                    "formId": "form-restore-play", "matchId": "restore-play-match"
                }]
            }
        }
        backup_path = self.temp_path / "restore-playback-backup.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("""() =>
            state.clips.some(x => x.id === 'restore-play-clip') &&
            state.forms.some(x => x.id === 'form-restore-play') &&
            state.matchAnalyses.some(x => x.id === 'restore-play-match') &&
            state.aiFormAnalyses.some(x => x.id === 'restore-play-ai')
        """, timeout=10000)
        page.reload(wait_until="load")
        page.wait_for_function("state.matchAnalyses.length === 1 && state.aiFormAnalyses.length === 1")
        links = page.evaluate("""() => ({
            matchClipId: state.matchAnalyses[0].clipId,
            matchStorageKey: state.matchAnalyses[0].videoStorageKey,
            clipReverse: state.clips[0].matchAnalysisIds,
            aiFormId: state.aiFormAnalyses[0].formId,
            aiMatchId: state.aiFormAnalyses[0].matchId,
            formReverse: state.forms[0].aiAnalysisIds,
            matchReverse: state.matchAnalyses[0].aiFormAnalysisIds
        })""")
        self.assertEqual(links["matchClipId"], "restore-play-clip", links)
        self.assertEqual(links["matchStorageKey"], "restore-play-clip", links)
        self.assertEqual(links["clipReverse"], ["restore-play-match"], links)
        self.assertEqual(links["aiFormId"], "form-restore-play", links)
        self.assertEqual(links["aiMatchId"], "restore-play-match", links)
        self.assertEqual(links["formReverse"], ["restore-play-ai"], links)
        self.assertEqual(links["matchReverse"], ["restore-play-ai"], links)
        page.evaluate("playSavedClip('restore-play-clip', 0)")
        page.wait_for_function("document.getElementById('matchVideo').readyState >= 2", timeout=10000)
        self.assertIn("保存動画の読み込み成功", page.locator("#videoMeta").inner_text())
        page.evaluate("playSavedForm('form-restore-play')")
        page.wait_for_function("document.getElementById('formVideo').readyState >= 2", timeout=10000)
        self.assertIn("保存フォーム動画の読み込み成功", page.locator("#formVideoPlaybackStatus").inner_text())

    def test_video_import_before_json_is_retried_after_json_and_keeps_ai_links(self):
        import json
        page = self.page
        self.accept_dialogs()
        video = self.temp_path / "riku-video__late-clip__late-match.mp4"
        video.write_bytes(self.video_path.read_bytes())
        page.locator("#videoImportFiles").set_input_files(str(video))
        self.wait_for_stage48_restore()
        pending = page.evaluate("""() => ({
            count:lastVideoImportFiles.length,
            name:lastVideoImportFiles[0]?.name,
            button:getComputedStyle(document.getElementById('videoImportRetry')).display !== 'none'
        })""")
        self.assertEqual(pending["count"], 1, pending)
        self.assertTrue(pending["button"], pending)
        backup = {
            "backupFormat":"riku-football-lab", "backupVersion":3,
            "videoFilesIncluded":False,
            "state":{
                "settings":{"name":"陸玖","jersey1":10,"jersey2":74,"apiBaseUrl":""},
                "menus":[],"trainings":[],"measures":[],
                "clips":[{"id":"late-clip","title":"後から復元した試合","hasVideo":False,"matchAnalysisIds":[]}],
                "forms":[{"id":"late-form","title":"フォーム","hasVideo":False,"aiAnalysisIds":[]}],
                "matchAnalyses":[{"id":"late-match","title":"試合分析","clipId":"late-clip","aiFormAnalysisIds":["late-ai"]}],
                "aiFormAnalyses":[{"id":"late-ai","title":"AIフォーム","formId":"late-form","matchId":"late-match"}]
            }
        }
        backup_path = self.temp_path / "late-video-json.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.some(x=>x.id==='late-clip') && state.matchAnalyses.some(x=>x.id==='late-match')")
        self.assertEqual(page.evaluate("lastVideoImportFiles.length"), 1)
        page.locator("#videoImportRetry").click()
        self.wait_for_stage48_restore()
        result = page.evaluate("""async () => ({
            retryCount:lastVideoImportFiles.length,
            videoSize:(await getClipVideo('late-clip'))?.blob?.size || 0,
            hasVideo:state.clips[0].hasVideo,
            clipLink:state.matchAnalyses[0].clipId,
            clipReverse:state.clips[0].matchAnalysisIds,
            aiForm:state.aiFormAnalyses[0].formId,
            aiMatch:state.aiFormAnalyses[0].matchId,
            formReverse:state.forms[0].aiAnalysisIds,
            matchReverse:state.matchAnalyses[0].aiFormAnalysisIds
        })""")
        self.assertEqual(result["retryCount"], 0, result)
        self.assertEqual(result["videoSize"], self.video_path.stat().st_size, result)
        self.assertTrue(result["hasVideo"], result)
        self.assertEqual(result["clipLink"], "late-clip", result)
        self.assertEqual(result["clipReverse"], ["late-match"], result)
        self.assertEqual(result["aiForm"], "late-form", result)
        self.assertEqual(result["aiMatch"], "late-match", result)
        self.assertEqual(result["formReverse"], ["late-ai"], result)
        self.assertEqual(result["matchReverse"], ["late-ai"], result)

    def test_json_before_video_restores_clip_and_form_media_with_analysis_links(self):
        import json
        page = self.page
        self.accept_dialogs()
        backup = {
            "backupFormat":"riku-football-lab", "backupVersion":3,
            "videoFilesIncluded":False,
            "state":{
                "settings":{"name":"陸玖","jersey1":10,"jersey2":74,"apiBaseUrl":""},
                "menus":[],"trainings":[],"measures":[],
                "clips":[{"id":"early-clip","title":"先にJSON","hasVideo":False,"matchAnalysisIds":[]}],
                "forms":[{"id":"early-form","title":"フォーム先行","hasVideo":False,"aiAnalysisIds":[]}],
                "matchAnalyses":[{"id":"early-match","title":"先行分析","clipId":"early-clip","aiFormAnalysisIds":["early-ai"]}],
                "aiFormAnalyses":[{"id":"early-ai","title":"AI分析","formId":"early-form","matchId":"early-match"}]
            }
        }
        backup_path = self.temp_path / "early-json-video.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.some(x=>x.id==='early-clip') && state.forms.some(x=>x.id==='early-form')")
        match_video = self.temp_path / "riku-video__early-clip__match.mp4"
        form_video = self.temp_path / "riku-video__form-early-form__form.mp4"
        match_video.write_bytes(self.video_path.read_bytes())
        form_video.write_bytes(self.video_path.read_bytes())
        page.locator("#videoImportFiles").set_input_files([str(match_video),str(form_video)])
        self.wait_for_stage48_restore()
        result = page.evaluate("""async () => ({
            clipBytes:(await getClipVideo('early-clip'))?.blob?.size || 0,
            formBytes:(await getClipVideo('form-early-form'))?.blob?.size || 0,
            clipHasVideo:state.clips[0].hasVideo,
            formHasVideo:state.forms[0].hasVideo,
            matchClipId:state.matchAnalyses[0].clipId,
            aiFormId:state.aiFormAnalyses[0].formId,
            aiMatchId:state.aiFormAnalyses[0].matchId,
            formReverse:state.forms[0].aiAnalysisIds,
            matchReverse:state.matchAnalyses[0].aiFormAnalysisIds
        })""")
        self.assertEqual(result["clipBytes"], self.video_path.stat().st_size, result)
        self.assertEqual(result["formBytes"], self.video_path.stat().st_size, result)
        self.assertTrue(result["clipHasVideo"], result)
        self.assertTrue(result["formHasVideo"], result)
        self.assertEqual(result["matchClipId"], "early-clip", result)
        self.assertEqual(result["aiFormId"], "early-form", result)
        self.assertEqual(result["aiMatchId"], "early-match", result)
        self.assertEqual(result["formReverse"], ["early-ai"], result)
        self.assertEqual(result["matchReverse"], ["early-ai"], result)

    def test_partial_video_first_restore_preserves_success_then_retries_only_missing_record_file(self):
        import json
        page = self.page
        self.accept_dialogs()
        page.evaluate("""() => {
            state.clips=[{id:'partial-existing',title:'先にある記録',hasVideo:false,matchAnalysisIds:[]}];
            state.forms=[];
            state.matchAnalyses=[{id:'partial-match-existing',clipId:'partial-existing',aiFormAnalysisIds:[]}];
            state.aiFormAnalyses=[];
            persist();
        }""")
        good = self.temp_path / "riku-video__partial-existing__good.mp4"
        pending = self.temp_path / "riku-video__partial-later__later.mp4"
        good.write_bytes(self.video_path.read_bytes())
        pending.write_bytes(self.video_path.read_bytes())
        page.locator("#videoImportFiles").set_input_files([str(good),str(pending)])
        self.wait_for_stage48_restore()
        first = page.evaluate("""async () => ({
            goodSize:(await getClipVideo('partial-existing'))?.blob?.size || 0,
            retryNames:lastVideoImportFiles.map(f=>f.name),
            goodFlag:state.clips[0].hasVideo
        })""")
        self.assertEqual(first["goodSize"], self.video_path.stat().st_size, first)
        self.assertTrue(first["goodFlag"], first)
        self.assertEqual(first["retryNames"], ["riku-video__partial-later__later.mp4"], first)
        backup = {
            "backupFormat":"riku-football-lab", "backupVersion":3,
            "videoFilesIncluded":False,
            "state":{
                "settings":{"name":"陸玖","jersey1":10,"jersey2":74,"apiBaseUrl":""},
                "menus":[],"trainings":[],"measures":[],
                "clips":[
                    {"id":"partial-existing","title":"先にある記録","hasVideo":False,"matchAnalysisIds":[]},
                    {"id":"partial-later","title":"後から復元する記録","hasVideo":False,"matchAnalysisIds":[]}
                ],
                "forms":[],
                "matchAnalyses":[
                    {"id":"partial-match-existing","clipId":"partial-existing","aiFormAnalysisIds":[]},
                    {"id":"partial-match-later","clipId":"partial-later","aiFormAnalysisIds":["partial-ai"]}
                ],
                "aiFormAnalyses":[{"id":"partial-ai","matchId":"partial-match-later"}]
            }
        }
        backup_path = self.temp_path / "partial-video-json.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.length===2 && state.matchAnalyses.length===2")
        page.locator("#videoImportRetry").click()
        self.wait_for_stage48_restore()
        result = page.evaluate("""async () => ({
            retryCount:lastVideoImportFiles.length,
            firstBytes:(await getClipVideo('partial-existing'))?.blob?.size || 0,
            secondBytes:(await getClipVideo('partial-later'))?.blob?.size || 0,
            flags:state.clips.map(x=>x.hasVideo),
            matchLinks:state.matchAnalyses.map(x=>x.clipId),
            aiMatch:state.aiFormAnalyses[0].matchId,
            aiReverse:state.matchAnalyses[1].aiFormAnalysisIds
        })""")
        self.assertEqual(result["retryCount"], 0, result)
        self.assertEqual(result["firstBytes"], self.video_path.stat().st_size, result)
        self.assertEqual(result["secondBytes"], self.video_path.stat().st_size, result)
        self.assertEqual(result["flags"], [True,True], result)
        self.assertEqual(result["matchLinks"], ["partial-existing","partial-later"], result)
        self.assertEqual(result["aiMatch"], "partial-match-later", result)
        self.assertEqual(result["aiReverse"], ["partial-ai"], result)

if __name__ == "__main__":
    unittest.main(verbosity=2)
