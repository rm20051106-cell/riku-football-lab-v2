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
        terminal = "全動画の復元とSHA-256照合が完了|完了（一部失敗）|安全停止した動画があります|再開対象がありません";
        self.page.wait_for_function("""(terminal) => {
            const text = document.getElementById('stage48Status')?.textContent || '';
            return !!text && !new RegExp(terminal).test(text);
        }""", arg=terminal, timeout=timeout)
        self.page.wait_for_function("""(terminal) => {
            const text = document.getElementById('stage48Status')?.textContent || '';
            return new RegExp(terminal).test(text);
        }""", arg=terminal, timeout=timeout)

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
        service_worker_source = page.evaluate("""async () => {
            const response = await fetch('./sw.js');
            if (!response.ok) throw new Error('Service worker source unavailable');
            return response.text();
        }""")
        self.assertIn("riku-global-mutation-lock.js", service_worker_source)
        self.assertIn("riku-football-lab-shell-v6", service_worker_source)

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
        titles = page.evaluate("""async () => {
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
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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

        page.evaluate("""async ({clipId, formId}) => window.withGlobalMutationLock('test-remove-videos', async () => {
            state.clips = [];
            state.forms = [];
            persist();
            await removeClipVideo(clipId);
            await removeClipVideo('form-' + formId);
        })""", {"clipId": clip_id, "formId": form_id})
        page.locator("#importFile").set_input_files(str(backup_path))
        page.wait_for_function("state.clips.length === 1 && state.forms.length === 1")
        page.evaluate("""async () => {
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
        page.evaluate("""async () => {
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
        page.evaluate("""async () => {
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
        failed = page.evaluate("""async () => {
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
            return await window.withGlobalMutationLock('test-fixture',()=>persist());
        }""")
        self.assertFalse(failed)
        self.assertFalse(page.locator("#recordSaveNotice").evaluate("(el) => el.classList.contains('hidden')"))
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="プレー分析を保存").click()
        self.assertEqual(page.evaluate("state.clips.length"), 0)
        self.assertFalse(page.locator("#recordSaveNotice").evaluate("(el) => el.classList.contains('hidden')"))

    def test_corrupt_json_backup_is_rejected_without_replacing_current_data(self):
        page = self.page
        page.evaluate("""async () => {
            state.settings.name = '保護する現在データ';
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.clips = [{id: 'restore-check-1', title: '復元照合', hasVideo: false}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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

    def test_video_replacement_preserves_unjournaled_generation_chunks(self):
        page = self.page
        result = page.evaluate("""async () => {
            await storeClipVideo('gc-check', new Blob([new Uint8Array([1, 2, 3])], {type: 'video/mp4'}));
            const db = await openVideoDB();
            try {
                await window.withGlobalMutationLock('test-fixture', async () => {
                    const ctx = window.__rikuMutationContext;
                    ctx.chunkWriteAuthorized = true;
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
                    } finally { ctx.chunkWriteAuthorized = false; }
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
        self.assertEqual(len(result["keys"]), 3, result)
        self.assertTrue(any(key.startswith(result["activePrefix"]) for key in result["keys"]), result)
        self.assertTrue(any("abandoned-generation" in key for key in result["keys"]), result)
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
                await window.withGlobalMutationLock('test-fixture', async () => {
                    const ctx = window.__rikuMutationContext;
                    ctx.videoMetadataWriteAuthorized = true;
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
                    } finally { ctx.videoMetadataWriteAuthorized = false; }
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
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.clips = [{
                id: 'import-identity-1', title: '元動画照合',
                hasVideo: false, sourceVideoKey: 'original.mp4|4|123|video/mp4'
            }];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
                await window.withGlobalMutationLock('test-fixture', async () => {
                    const ctx = window.__rikuMutationContext;
                    ctx.chunkDeleteAuthorized = true;
                    try {
                        await new Promise((resolve, reject) => {
                            const tx = db.transaction('videoChunks', 'readwrite');
                            tx.objectStore('videoChunks').delete(record.chunkPrefix + '00000000');
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally {
                        ctx.chunkDeleteAuthorized = false;
                    }
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
        page.evaluate("""async () => {
            state.clips = [{
                id: 'batch-good', title: '正常動画', hasVideo: false,
                sourceVideoKey: ''
            }];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
        }""")
        good_video = self.temp_path / "riku-video__batch-good__good.webm"
        missing_record_video = self.temp_path / "riku-video__missing-record__lost.webm"
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
            result["retryNames"], ["riku-video__missing-record__lost.webm"], result
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
                await window.withGlobalMutationLock('test-fixture', async () => {
                    const ctx = window.__rikuMutationContext;
                    ctx.chunkDeleteAuthorized = true;
                    try {
                        await new Promise((resolve, reject) => {
                            const tx = db.transaction('videoChunks', 'readwrite');
                            tx.objectStore('videoChunks').delete(record.chunkPrefix + '00000000');
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally {
                        ctx.chunkDeleteAuthorized = false;
                    }
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
        video_path = self.temp_path / "riku-video__restore-order-1__order.webm"
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

        page.locator('.nav button[data-view="settings"]').click()
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
        self.assertEqual(repeated, {"count": 1, "bytes": self.video_path.stat().st_size, "retryCount": 0})


    def test_invalid_json_restore_preserves_current_state_and_storage(self):
        page = self.page
        page.evaluate("""async () => {
            state.clips = [{id: 'keep-existing', title: '保持する記録', hasVideo: false}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.clips = [{id: 'storage-keep', title: '保存保護', hasVideo: false}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        after = page.evaluate("""async () => {
            Storage.prototype.setItem = window.__originalStorageSetItem;
            return {state: JSON.stringify(state), stored: localStorage.getItem(KEY)};
        }""")
        self.assertEqual(after, before)
        self.assertTrue(any("再読み込みせず" in message for message in messages), messages)


    def test_delete_clip_detaches_match_and_ai_references_without_deleting_other_records(self):
        page = self.page
        page.evaluate("""async () => {
            const key = 'clip-delete.mp4|4|123|video/mp4';
            state.clips = [{id: 'clip-delete', sourceVideoKey: key, hasVideo: true, matchAnalysisIds: ['match-keep']}];
            state.forms = [{id: 'form-keep', sourceVideoKey: 'form.mp4|4|124|video/mp4', hasVideo: false, aiAnalysisIds: ['ai-keep']}];
            state.matchAnalyses = [{id: 'match-keep', sourceVideoKey: key, clipId: 'clip-delete', videoStorageKey: 'clip-delete', aiFormAnalysisIds: ['ai-keep']}];
            state.aiFormAnalyses = [{id: 'ai-keep', sourceVideoKey: key, formId: 'form-keep', matchId: 'match-keep', matchClipId: 'clip-delete'}];
            await storeClipVideo('clip-delete', new Blob([new Uint8Array([1,2,3,4])], {type: 'video/mp4'}));
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.matchAnalyses = [{id: 'match-delete', title: '削除対象', aiFormAnalysisIds: ['ai-keep']}];
            state.clips = [{id: 'clip-keep', matchAnalysisIds: ['match-delete']}];
            state.aiFormAnalyses = [{id: 'ai-keep', matchId: 'match-delete', matchTitle: '削除対象', matchDate: '2026-11-01', matchClipId: 'clip-keep'}];
            state.forms = [{id: 'form-keep', aiAnalysisIds: ['ai-keep']}];
            state.trainings = [{id: 'training-keep', linkedMatchEvents: [{matchId: 'match-delete', eventId: 'event-1'}], sourceMatch: {matchId: 'match-delete', eventId: 'event-2'}}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.aiFormAnalyses = [{id: 'ai-delete-rollback'}];
            state.forms = [{id: 'form-rollback', aiAnalysisIds: ['ai-delete-rollback']}];
            state.matchAnalyses = [{id: 'match-rollback', aiFormAnalysisIds: ['ai-delete-rollback']}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.evaluate("""async () => {
            state.aiFormAnalyses = [{id: 'ai-delete'}];
            state.forms = [{id: 'form-keep', aiAnalysisIds: ['ai-delete', 'ai-other']}];
            state.matchAnalyses = [{id: 'match-keep', aiFormAnalysisIds: ['ai-delete', 'ai-other']}];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        page.evaluate("pendingMatchSave")
        page.evaluate("""async () => {
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
            await saveMatchScanResult();
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
        playback_events = []
        page.evaluate("""async () => {
            const v = document.getElementById('matchVideo');
            window.__savedPlaybackEvents = [];
            ['loadstart','loadedmetadata','loadeddata','canplay','canplaythrough','error','abort','stalled','suspend'].forEach(name =>
                v.addEventListener(name, () => window.__savedPlaybackEvents.push({
                    name, readyState: v.readyState, networkState: v.networkState,
                    errorCode: v.error?.code || null, currentSrc: v.currentSrc
                }))
            );
        }""")
        page.get_by_role("button", name="端末内動画を再生").first.click()
        page.wait_for_timeout(2500)
        playback_diagnostics = page.evaluate("""async () => {
            const v = document.getElementById('matchVideo');
            const saved = await getClipVideo(state.clips[0].id);
            return {
                readyState: v.readyState, networkState: v.networkState,
                errorCode: v.error?.code || null, errorMessage: v.error?.message || null,
                currentSrc: v.currentSrc, videoMeta: document.getElementById('videoMeta').textContent,
                srcAssigned: !!v.src, paused: v.paused, duration: v.duration,
                events: window.__savedPlaybackEvents || [],
                saved: saved ? {size: saved.blob?.size, type: saved.blob?.type,
                    storageFormat: saved.storageFormat, chunkCount: saved.chunkCount,
                    name: saved.name} : null
            };
        }""")
        self.assertGreaterEqual(playback_diagnostics["readyState"], 2, playback_diagnostics)


    def test_positioning_summary_and_weekly_plan_use_only_confirmed_manual_reviews(self):
        result = self.page.evaluate("""async () => {
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
            const saved = await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        page.evaluate("""async () => {
            state.settings.apiBaseUrl = 'https://riku-upload-mock.invalid';
            await window.withGlobalMutationLock('test-fixture',()=>persist());
            window.__matchStatusFetchTrace = [];
            const originalFetch = window.fetch.bind(window);
            window.fetch = function(input, init) {
                const url = typeof input === 'string' ? input : input?.url || '';
                if (String(url).includes('/analyze/jobs/')) {
                    window.__matchStatusFetchTrace.push({
                        at: performance.now(), url: String(url),
                        stack: String(new Error().stack || '').split('\\n').slice(0, 6)
                    });
                }
                return originalFetch(input, init);
            };
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
                "() => document.querySelector('#matchAiResult button')?.textContent.includes('このAI解析結果を履歴に保存')",
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
        job_requests = []
        def mock_restore_job(route):
            job_requests.append({"method": route.request.method, "url": route.request.url})
            route.fulfill(
                status=200,
                headers={"Access-Control-Allow-Origin": "*"},
                content_type="application/json",
                body=json.dumps(
                    {"ok": True} if route.request.url.endswith("/health") else {
                        "job_id": "restore-job-123", "status": "completed", "progress": 100, "stage": "完了",
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
            )
        page_errors = []
        console_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.route(api_base + "/**", mock_restore_job)
        metadata = page.evaluate("""async (apiBase) => {
            state.matchAnalyses = [];
            state.settings.apiBaseUrl = apiBase;
            await window.withGlobalMutationLock('test-fixture',()=>persist());
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
        page.wait_for_timeout(6000)
        restore_diagnostics = page.evaluate("""async (diagnostics) => ({
            text: document.getElementById('matchAiResult').textContent,
            apiBaseUrl: state.settings.apiBaseUrl,
            pending: await getPendingMatchJob(),
            savedMatches: state.matchAnalyses.length,
            requestSeen: performance.getEntriesByType('resource').map(x => x.name).filter(x => x.includes('restore-match-job-mock.invalid')),
            settingsRaw: localStorage.getItem(KEY),
            startupReady: document.readyState,
            restoreDiagnostics: window.__matchRestoreDiagnostics || null,
            restoreFunctionType: typeof resumePendingMatchJob,
            resultElementCount: document.querySelectorAll('#matchAiResult').length,
            pageErrors: diagnostics.pageErrors,
            consoleErrors: diagnostics.consoleErrors
        })""", {"pageErrors": page_errors, "consoleErrors": console_errors})
        self.assertIn("全編スキャンが完了しました", restore_diagnostics["text"],
                      {"diagnostics": restore_diagnostics, "requests": job_requests})
        self.assertIn("このAI解析結果を履歴に保存", page.locator("#matchAiResult").inner_text())
        # The result panel lives in the video view; reveal it before interacting with its button.
        page.evaluate("showView('video')")
        # A local persistence failure must not discard the only recoverable job pointer.
        button_diagnostics = page.locator("#matchAiResult").evaluate("""el => ({
            html: el.innerHTML,
            buttons: [...el.querySelectorAll("button")].map(button => ({
                text: button.innerText,
                outerHTML: button.outerHTML,
                visible: !!(button.offsetWidth || button.offsetHeight || button.getClientRects().length)
            }))
        })""")
        self.assertTrue(button_diagnostics["buttons"], button_diagnostics)
        self.assertTrue(button_diagnostics["buttons"][-1]["visible"],
                        {"buttons": button_diagnostics, "activeVideo": page.locator("#video").get_attribute("class")})
        self.assertTrue(page.locator("#matchAiResult button").last.is_visible(), button_diagnostics)
        page.evaluate("""async () => {
            window.__originalMatchPersist = window.persist;
            window.persist = () => false;
        }""")
        page.locator("#matchAiResult button").last.evaluate("(button) => button.click()")
        retry_button = page.locator("#matchAiResult button").filter(has_text="保存を再試行")
        retry_button.wait_for(state="visible", timeout=5000)
        failed_save = page.evaluate("""async () => ({
            count: state.matchAnalyses.length,
            savedId: document.getElementById('matchAiResult').dataset.savedId || null,
            pending: await getPendingMatchJob()
        })""")
        self.assertEqual(failed_save["count"], 0, failed_save)
        self.assertIsNone(failed_save["savedId"], failed_save)
        self.assertEqual(failed_save["pending"]["jobId"], "restore-job-123", failed_save)
        page.evaluate("""async () => {
            window.persist = window.__originalMatchPersist;
            delete window.__originalMatchPersist;
            window.__matchSaveTrace = [];
            window.__matchSaveSnapshots = [];
            window.__matchSaveMonitor = setInterval(() => {
                let stored = [];
                try { stored = (JSON.parse(localStorage.getItem(KEY) || '{}').matchAnalyses || []).map(row => row.id); } catch (_) {}
                window.__matchSaveSnapshots.push({
                    at: performance.now(),
                    ids: (state.matchAnalyses || []).map(row => row.id),
                    stored
                });
            }, 250);
            const originalPersist = window.persist;
            window.persist = function() {
                const before = (state.matchAnalyses || []).map(row => row.id);
                const result = originalPersist.apply(this, arguments);
                window.__matchSaveTrace.push({
                    op: 'persist', before, after: (state.matchAnalyses || []).map(row => row.id),
                    stored: (() => { try { return (JSON.parse(localStorage.getItem(KEY) || '{}').matchAnalyses || []).map(row => row.id); } catch (e) { return 'parse-error'; } })(),
                    result
                });
                return result;
            };
            const originalClear = window.clearPendingMatchJob;
            window.clearPendingMatchJob = async function() {
                window.__matchSaveTrace.push({op:'clear-start', ids:(state.matchAnalyses||[]).map(row=>row.id)});
                let timer;
                try {
                    const result = await Promise.race([
                        originalClear.apply(this, arguments),
                        new Promise(resolve => { timer = setTimeout(() => resolve('__diagnostic_timeout__'), 4000); })
                    ]);
                    if (result === '__diagnostic_timeout__') {
                        window.__matchSaveTrace.push({op:'clear-timeout', ids:(state.matchAnalyses||[]).map(row=>row.id)});
                        return;
                    }
                    window.__matchSaveTrace.push({op:'clear-end', ids:(state.matchAnalyses||[]).map(row=>row.id)});
                    return result;
                } finally { if (timer) clearTimeout(timer); }
            };
            const originalLoad = window.load;
            window.load = function() {
                window.__matchSaveTrace.push({op:'load-before', ids:(state.matchAnalyses||[]).map(row=>row.id)});
                const result = originalLoad.apply(this, arguments);
                window.__matchSaveTrace.push({op:'load-after', ids:(state.matchAnalyses||[]).map(row=>row.id)});
                return result;
            };
        }""")
        page.evaluate("""async () => {
            window.__matchIdbTrace = [];
            const trace = (event, detail={}) => window.__matchIdbTrace.push({at:performance.now(),event,...detail});
            try {
                const factoryProto = IDBFactory.prototype;
                const originalOpen = factoryProto.open;
                factoryProto.open = function() {
                    const args = [...arguments], req = originalOpen.apply(this, args);
                    trace('open-called', {name:String(args[0]),version:args[1]??null});
                    req.addEventListener('blocked', () => trace('open-blocked', {name:String(args[0])}));
                    req.addEventListener('error', () => trace('open-error', {name:String(args[0]),error:String(req.error)}));
                    req.addEventListener('success', () => trace('open-success', {name:String(args[0]),dbVersion:req.result.version}));
                    return req;
                };
                const dbProto = IDBDatabase.prototype;
                const originalTransaction = dbProto.transaction;
                dbProto.transaction = function() {
                    const args = [...arguments], tx = originalTransaction.apply(this,args);
                    const stores = Array.isArray(args[0]) ? args[0] : [args[0]];
                    trace('tx-created',{db:this.name,stores:stores.map(String),mode:args[1]||'readonly'});
                    for (const event of ['complete','abort','error']) tx.addEventListener(event,()=>trace('tx-'+event,{db:this.name,stores:stores.map(String),error:tx.error?String(tx.error):null}));
                    return tx;
                };
                const storeProto = IDBObjectStore.prototype;
                const originalDelete = storeProto.delete;
                storeProto.delete = function(key) {
                    const req = originalDelete.call(this,key);
                    trace('delete-called',{store:this.name,key:String(key)});
                    req.addEventListener('success',()=>trace('delete-success',{store:this.name,key:String(key)}));
                    req.addEventListener('error',()=>trace('delete-error',{store:this.name,key:String(key),error:String(req.error)}));
                    return req;
                };
            } catch (error) { trace('instrumentation-error',{error:String(error)}); }
        }""")
        retry_button.click()
        page.wait_for_function("() => state.matchAnalyses.length === 1 && (window.__matchSaveTrace || []).some(item => ['clear-end','clear-timeout'].includes(item.op))", timeout=10000)
        saved = page.evaluate("""async (diagnostics) => {
            const persisted = JSON.parse(localStorage.getItem(KEY) || '{}');
            return {
                count: state.matchAnalyses.length,
                stateMatchIds: (state.matchAnalyses || []).map(row => row.id),
                persistedCount: (persisted.matchAnalyses || []).length,
                persistedMatchIds: (persisted.matchAnalyses || []).map(row => row.id),
                record: state.matchAnalyses[0] || null,
                pending: await getPendingMatchJob(),
                savedId: document.getElementById('matchAiResult').dataset.savedId || null,
                restoreDiagnostics: window.__matchRestoreDiagnostics || null,
                saveTrace: window.__matchSaveTrace || [],
                idbTrace: window.__matchIdbTrace || [],
                saveSnapshots: window.__matchSaveSnapshots || [],
                statusFetchTrace: window.__matchStatusFetchTrace || [],
                pageErrors: diagnostics.pageErrors,
                consoleErrors: diagnostics.consoleErrors,
                historyText: document.getElementById('matchScanRecords').innerText
            };
        }""", {"pageErrors": page_errors, "consoleErrors": console_errors})
        print("MATCH_SAVE_DIAGNOSTICS=" + json.dumps({
            "saveTrace": saved["saveTrace"],
            "idbTrace": saved["idbTrace"],
            "pending": saved["pending"],
            "persistedCount": saved["persistedCount"],
        }, ensure_ascii=False, default=str), flush=True)
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
            page.evaluate("""async () => { state.settings.apiBaseUrl = 'https://riku-resume-mock.invalid'; await window.withGlobalMutationLock('test-fixture',()=>persist()); }""")
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
            page.evaluate("""async () => {
                state.settings.apiBaseUrl = 'https://riku-webkit-mock.invalid';
                await window.withGlobalMutationLock('test-fixture',()=>persist());
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
            page.evaluate("""async () => {
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
        page.evaluate("""async () => { state.settings.apiBaseUrl = window.location.origin; await window.withGlobalMutationLock('test-fixture',()=>persist()); }""")
        page.locator('.nav button[data-view="video"]').click()
        page.locator("#videoTitle").fill("実動画履歴復元メタデータ")
        page.locator("#videoFile").set_input_files(str(self.video_path))
        page.evaluate("""async () => {
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
        saved = page.evaluate("""async () => {
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
        restored = page.evaluate("""async () => {
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
        result = page.evaluate("""async () => {
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
                await window.withGlobalMutationLock('test-fixture', async () => {
                    const ctx = window.__rikuMutationContext;
                    ctx.chunkWriteAuthorized = true;
                    try {
                        await new Promise((resolve, reject) => {
                            const tx = db.transaction('videoChunks', 'readwrite');
                            tx.objectStore('videoChunks').put(new Uint8Array([9,9]), 'missing-owner|old-generation|00000000');
                            tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
                        });
                    } finally { ctx.chunkWriteAuthorized = false; }
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
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
        result = self.page.evaluate("""async () => {
            const current = {clips:[{id:'before'}], matchAnalyses:[]};
            const snapshot = createBackupStateSnapshot(current);
            current.clips.push({id:'after'});
            return {snapshotIds:snapshot.clips.map(x=>x.id),liveIds:current.clips.map(x=>x.id)};
        }""")
        self.assertEqual(result["snapshotIds"], ["before"])
        self.assertEqual(result["liveIds"], ["before", "after"])

    def test_reimporting_same_video_backup_twice_skips_without_duplicate_storage(self):
        page = self.page
        page.evaluate("""async () => {
            state.clips = [{id:'repeat-video', title:'同一動画', hasVideo:false}];
            state.forms = []; await window.withGlobalMutationLock('test-fixture',()=>persist());
        }""")
        video = self.temp_path / "riku-video__repeat-video__repeat.webm"
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
        result = self.page.evaluate("""async () => {
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
        video = self.temp_path / "riku-video__late-clip__late-match.webm"
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
        page.locator('.nav button[data-view="settings"]').click()
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
        match_video = self.temp_path / "riku-video__early-clip__match.webm"
        form_video = self.temp_path / "riku-video__form-early-form__form.webm"
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
        page.evaluate("""async () => {
            state.clips=[{id:'partial-existing',title:'先にある記録',hasVideo:false,matchAnalysisIds:[]}];
            state.forms=[];
            state.matchAnalyses=[{id:'partial-match-existing',clipId:'partial-existing',aiFormAnalysisIds:[]}];
            state.aiFormAnalyses=[];
            await window.withGlobalMutationLock('test-fixture',()=>persist());
        }""")
        good = self.temp_path / "riku-video__partial-existing__good.webm"
        pending = self.temp_path / "riku-video__partial-later__later.webm"
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
        self.assertEqual(first["retryNames"], ["riku-video__partial-later__later.webm"], first)
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
        page.locator('.nav button[data-view="settings"]').click()
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


    def test_webkit_20_minute_match_upload_frontend_completion_flow(self):
        browser = self.playwright.webkit.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof saveClip === 'function'")
            page.locator('.nav button[data-view="video"]').click()
            page.evaluate("""async () => {
                state.settings.apiBaseUrl = 'https://riku-webkit-20min-mock.invalid';
                await window.withGlobalMutationLock('test-fixture',()=>persist());
            }""")
            counters = {"created": 0, "chunks": [], "completed": 0, "status": 0}
            def mock_api(route):
                request = route.request
                if not request.url.startswith("https://riku-webkit-20min-mock.invalid/"):
                    route.continue_()
                    return
                path = request.url.split("riku-webkit-20min-mock.invalid", 1)[-1]
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
                                  body=json.dumps({"ok": True, "upload_id": "webkit-20min-upload",
                                                   "chunk_size": counters["chunk_size"],
                                                   "total_chunks": (counters["size"] + counters["chunk_size"] - 1) // counters["chunk_size"]}))
                elif path.startswith("/analyze/match/uploads/webkit-20min-upload/") and request.method == "PUT":
                    index = int(path.rsplit("/", 1)[-1])
                    counters["chunks"].append(index)
                    received_bytes = min(counters["size"], (index + 1) * counters["chunk_size"])
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "chunk_index": index,
                                                   "received_bytes": received_bytes,
                                                   "total_bytes": counters["size"]}))
                elif path == "/analyze/match/uploads/webkit-20min-upload/complete" and request.method == "POST":
                    counters["completed"] += 1
                    route.fulfill(status=202, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok": True, "job_id": "webkit-20min-job", "status": "queued"}))
                elif path == "/analyze/jobs/webkit-20min-job":
                    counters["status"] += 1
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"status": "completed", "progress": 100, "stage": "完了",
                                                   "result": {"job_id": "webkit-20min-job", "summary": {
                                                       "duration_seconds": 1200, "sampled_pose_frames": 0,
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
                "name": "webkit-synthetic-20min.mp4",
                "mimeType": "video/mp4",
                "buffer": b"V" * (13 * 1024 * 1024 + 19),
            })
            page.wait_for_function(
                "() => document.getElementById('videoFile').files.length === 1",
                timeout=5000,
            )
            page.evaluate("""async () => {
                Object.defineProperty(document.getElementById('matchVideo'), 'duration',
                                      {configurable: true, value: 1200});
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
            self.assertEqual(counters["chunks"], [0, 1, 2])
            self.assertIn("20", page.locator("#matchAiResult").inner_text())

        finally:
            context.close()
            browser.close()

    def test_webkit_interrupted_match_upload_resumes_after_reload(self):
        browser = self.playwright.webkit.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        page = context.new_page()
        try:
            page.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof uploadMatchVideoInChunks === 'function'")
            page.locator('.nav button[data-view="video"]').click()
            page.evaluate("""async () => {
                state.settings.apiBaseUrl = 'https://riku-interrupt-mock.invalid';
                await window.withGlobalMutationLock('test-fixture',()=>persist());
            }""")
            page.locator("#videoFile").set_input_files({
                "name": "same-source-interrupted.mp4", "mimeType": "video/mp4",
                "buffer": b"\xcd" * (6 * 1024 * 1024 * 2 + 37),
            })
            page.wait_for_function("() => document.getElementById('videoFile').files.length === 1")
            source = page.evaluate("""async () => {
                const file = document.getElementById('videoFile').files[0];
                await storeClipVideo('__pending_match_video__', file);
                return {size:file.size, sourceKey:getVideoSourceKey(file),
                        fingerprint:await getVideoContentFingerprint(file)};
            }""")
            snapshot_script = r"""
            async () => {
                const KEY = 'rikuFootballLab_v3';
                const EXCLUDED_VIDEO_KEYS = new Set([
                    '__pending_match_upload__',
                    '__pending_match_job__'
                ]);
                const hex = buffer =>
                    Array.from(new Uint8Array(buffer),
                        byte => byte.toString(16).padStart(2, '0')).join('');
                const sha256 = async buffer =>
                    hex(await crypto.subtle.digest('SHA-256', buffer));
                const copyViewBytes = view => new Uint8Array(view.buffer, view.byteOffset, view.byteLength).slice().buffer;
                const keyValue = key => {
                    if (key instanceof Date) return {type:'date', value:key.toISOString()};
                    if (key instanceof ArrayBuffer) return {type:'binary', value:hex(key)};
                    if (ArrayBuffer.isView(key)) {
                        const bytes = copyViewBytes(key);
                        return {type:'binary', value:hex(bytes)};
                    }
                    if (Array.isArray(key)) return {type:'array', value:key.map(keyValue)};
                    return {type:typeof key, value:String(key)};
                };
                const encode = async (value, seen = new WeakSet()) => {
                    if (value === null) return null;
                    if (value === undefined) return {type:'undefined'};
                    if (value instanceof Blob) return {
                        type:'Blob', mime:value.type, size:value.size,
                        sha256:await sha256(await value.arrayBuffer())
                    };
                    if (value instanceof ArrayBuffer) return {
                        type:'ArrayBuffer', size:value.byteLength, sha256:await sha256(value)
                    };
                    if (ArrayBuffer.isView(value)) {
                        const bytes = copyViewBytes(value);
                        return {type:value.constructor.name, byteLength:value.byteLength, sha256:await sha256(bytes)};
                    }
                    if (value instanceof Date) return {type:'Date', value:value.toISOString()};
                    if (typeof value !== 'object') return value;
                    if (seen.has(value)) throw new Error('Unexpected cyclic value in snapshot');
                    seen.add(value);
                    try {
                        if (Array.isArray(value)) {
                            const result = [];
                            for (const item of value) result.push(await encode(item, seen));
                            return result;
                        }
                        const result = {};
                        for (const key of Object.keys(value).sort()) result[key] = await encode(value[key], seen);
                        return result;
                    } finally {
                        seen.delete(value);
                    }
                };
                const digestObject = async value => {
                    const encoded = await encode(value);
                    return sha256(new TextEncoder().encode(JSON.stringify(encoded)));
                };
                const requestResult = request => new Promise((resolve, reject) => {
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'));
                });

                const db = await openVideoDB();
                let idbData;
                try {
                    const tx = db.transaction(['videos', 'videoChunks'], 'readonly');
                    const txDone = new Promise((resolve, reject) => {
                        tx.oncomplete = resolve;
                        tx.onerror = () => reject(tx.error || new Error('IndexedDB transaction error'));
                        tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted'));
                    });
                    const videosStore = tx.objectStore('videos');
                    const chunksStore = tx.objectStore('videoChunks');
                    const videoValuesRequest = videosStore.getAll();
                    const videoKeysRequest = videosStore.getAllKeys();
                    const chunkValuesRequest = chunksStore.getAll();
                    const chunkKeysRequest = chunksStore.getAllKeys();
                    const [videoValues, videoKeys, chunkValues, chunkKeys] = await Promise.all([
                        requestResult(videoValuesRequest),
                        requestResult(videoKeysRequest),
                        requestResult(chunkValuesRequest),
                        requestResult(chunkKeysRequest)
                    ]);
                    await txDone;
                    if (videoValues.length !== videoKeys.length || chunkValues.length !== chunkKeys.length) {
                        throw new Error('IndexedDB key/value count mismatch');
                    }
                    idbData = {
                        videoRows: videoKeys.map((key, index) => ({key:keyValue(key), rawKey:key, value:videoValues[index]})),
                        chunkRows: chunkKeys.map((key, index) => ({key:keyValue(key), value:chunkValues[index]}))
                    };
                } finally {
                    db.close();
                }

                const sortRows = rows => rows.sort((a,b) => {
                    const left = JSON.stringify(a.key), right = JSON.stringify(b.key);
                    return left < right ? -1 : left > right ? 1 : 0;
                });
                const stableVideos = sortRows(idbData.videoRows
                    .filter(row => !EXCLUDED_VIDEO_KEYS.has(String(row.rawKey)))
                    .map(({key,value}) => ({key,value})));
                const stableChunks = sortRows(idbData.chunkRows);
                const pendingMap = new Map(idbData.videoRows.map(row => [String(row.rawKey), row.value]));
                const pendingUpload = pendingMap.get('__pending_match_upload__') ?? null;
                const pendingJob = pendingMap.get('__pending_match_job__') ?? null;

                const rawStorage = localStorage.getItem(KEY);
                let savedState = null;
                if (rawStorage !== null) {
                    try { savedState = JSON.parse(rawStorage); }
                    catch (error) { throw new Error('Saved localStorage JSON is invalid: ' + String(error)); }
                }
                const arrayNames = ['matchAnalyses', 'forms', 'aiFormAnalyses'];
                const liveArrays = {}, savedArrays = {};
                for (const name of arrayNames) {
                    const liveValue = state?.[name] ?? [];
                    const savedValue = savedState?.[name] ?? [];
                    if (!Array.isArray(liveValue) || !Array.isArray(savedValue)) {
                        throw new Error('Expected array state: ' + name);
                    }
                    liveArrays[name] = liveValue;
                    savedArrays[name] = savedValue;
                }
                return {
                    localStorageKey:KEY,
                    localStoragePresent:rawStorage !== null,
                    localStorageSha256:rawStorage === null ? null :
                        await sha256(new TextEncoder().encode(rawStorage)),
                    stateArraysSha256:await digestObject(liveArrays),
                    savedArraysSha256:await digestObject(savedArrays),
                    videosCount:stableVideos.length,
                    videosSha256:await digestObject(stableVideos),
                    videoChunksCount:stableChunks.length,
                    videoChunksSha256:await digestObject(stableChunks),
                    pendingUpload:pendingUpload === null ? null : await encode(pendingUpload),
                    pendingJob:pendingJob === null ? null : await encode(pendingJob)
                };
            }
            """

            protected_before = page.evaluate(snapshot_script)
            self.assertIsNone(protected_before["pendingUpload"])
            self.assertIsNone(protected_before["pendingJob"])

            server = {"size": source["size"], "chunkSize": 6 * 1024 * 1024,
                      "nextChunk": 0, "receivedBytes": 0, "puts": [], "abortSecondAttempts": 3,
                      "created": 0, "completed": 0, "status": 0}
            def mock_api(route):
                request = route.request
                if not request.url.startswith("https://riku-interrupt-mock.invalid/"):
                    route.continue_()
                    return
                path = request.url.split("riku-interrupt-mock.invalid", 1)[-1]
                headers = {"Access-Control-Allow-Origin":"*",
                           "Access-Control-Allow-Methods":"GET, POST, PUT, DELETE, OPTIONS",
                           "Access-Control-Allow-Headers":"*"}
                if request.method == "OPTIONS":
                    route.fulfill(status=204, headers=headers)
                elif path == "/analyze/match/uploads" and request.method == "POST":
                    server["created"] += 1
                    route.fulfill(status=201, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"upload_id":"interrupted-upload",
                                                   "chunk_size":server["chunkSize"],"total_chunks":3}))
                elif path == "/analyze/match/uploads/interrupted-upload" and request.method == "GET":
                    server["status"] += 1
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"upload_id":"interrupted-upload",
                                                   "next_chunk":server["nextChunk"],
                                                   "chunk_size":server["chunkSize"],"total_chunks":3,
                                                   "received_bytes":server["receivedBytes"],
                                                   "total_bytes":server["size"],"complete":False}))
                elif path.startswith("/analyze/match/uploads/interrupted-upload/") and request.method == "PUT":
                    index = int(path.rsplit("/",1)[-1])
                    server["puts"].append(index)
                    if index == 1 and server["abortSecondAttempts"] > 0:
                        server["abortSecondAttempts"] -= 1
                        route.abort("failed")
                        return
                    server["nextChunk"] = index + 1
                    server["receivedBytes"] = min(server["size"], server["nextChunk"] * server["chunkSize"])
                    route.fulfill(status=200, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"chunk_index":index,
                                                   "received_bytes":server["receivedBytes"],
                                                   "total_bytes":server["size"]}))
                elif path == "/analyze/match/uploads/interrupted-upload/complete" and request.method == "POST":
                    server["completed"] += 1
                    route.fulfill(status=202, headers=headers, content_type="application/json",
                                  body=json.dumps({"ok":True,"job_id":"interrupted-job","status":"queued"}))
                else:
                    route.fulfill(status=404, headers=headers, content_type="application/json",
                                  body=json.dumps({"detail":"unexpected request: "+path}))
            page.route("**/*", mock_api)
            first = page.evaluate("""async () => {
                const stored = await getClipVideo('__pending_match_video__');
                const file = new File([stored.blob], stored.name,
                    {type:stored.type, lastModified:stored.lastModified});
                let error = '';
                try { await uploadMatchVideoInChunks(file, '10,74', document.getElementById('matchAiResult')); }
                catch (e) { error = String(e); }
                const pending = await getPendingMatchUpload();
                return {error, pending, sourceKey:getVideoSourceKey(file),
                        fingerprint:await getVideoContentFingerprint(file)};
            }""")
            self.assertTrue(first["error"], first)
            self.assertIsNotNone(first["pending"], first)
            self.assertEqual(first["pending"]["nextChunk"], 1, first)
            self.assertEqual(first["sourceKey"], source["sourceKey"], first)
            self.assertEqual(first["fingerprint"], source["fingerprint"], first)
            self.assertEqual(server["puts"], [0, 1, 1, 1], server)

            page.reload(wait_until="load")
            page.wait_for_function("typeof uploadMatchVideoInChunks === 'function'")
            resumed = page.evaluate("""async () => {
                const stored = await getClipVideo('__pending_match_video__');
                if (!stored || !(stored.blob instanceof Blob))
                    throw new Error('same source video missing after reload');
                const file = new File([stored.blob], stored.name,
                    {type:stored.type, lastModified:stored.lastModified});
                const result = await uploadMatchVideoInChunks(
                    file, '10,74', document.getElementById('matchAiResult'));
                return {jobId:result.job_id, size:file.size,
                        pending:await getPendingMatchUpload(),
                        sourceKey:getVideoSourceKey(file),
                        fingerprint:await getVideoContentFingerprint(file)};
            }""")
            self.assertEqual(resumed["jobId"], "interrupted-job", resumed)
            self.assertEqual(resumed["size"], source["size"], resumed)
            self.assertEqual(resumed["sourceKey"], source["sourceKey"], resumed)
            self.assertEqual(resumed["fingerprint"], source["fingerprint"], resumed)
            self.assertIsNone(resumed["pending"], resumed)
            self.assertEqual(server["created"], 1, server)
            # Three failed chunk-1 attempts each reconcile server state; reload adds one resume lookup.
            self.assertEqual(server["status"], 4, server)
            self.assertEqual(server["puts"], [0, 1, 1, 1, 1, 2], server)
            self.assertEqual(server["completed"], 1, server)
            saved = page.evaluate("""async () => {
                const video = await getClipVideo('__pending_match_video__');
                return {size:video?.blob?.size || 0, name:video?.name || ''};
            }""")
            self.assertEqual(saved["size"], source["size"], saved)
            self.assertEqual(saved["name"], "same-source-interrupted.mp4", saved)
            protected_after = page.evaluate(snapshot_script)
            self.assertEqual(protected_after["videosCount"], protected_before["videosCount"], protected_after)
            self.assertEqual(protected_after["videosSha256"], protected_before["videosSha256"], protected_after)
            self.assertEqual(protected_after["videoChunksCount"], protected_before["videoChunksCount"], protected_after)
            self.assertEqual(protected_after["videoChunksSha256"], protected_before["videoChunksSha256"], protected_after)
            self.assertEqual(protected_after["localStorageKey"], protected_before["localStorageKey"])
            self.assertEqual(protected_after["localStoragePresent"], protected_before["localStoragePresent"])
            self.assertEqual(protected_after["localStorageSha256"], protected_before["localStorageSha256"], protected_after)
            self.assertEqual(protected_after["stateArraysSha256"], protected_before["stateArraysSha256"], protected_after)
            self.assertEqual(protected_after["savedArraysSha256"], protected_before["savedArraysSha256"], protected_after)
            self.assertIsNone(protected_after["pendingUpload"])
            self.assertIsNotNone(protected_after["pendingJob"])
            self.assertEqual(protected_after["pendingJob"]["jobId"], "interrupted-job")
            self.assertEqual(protected_after["pendingJob"]["sourceKey"], source["sourceKey"])
            self.assertEqual(protected_after["pendingJob"]["filename"], "same-source-interrupted.mp4")
            self.assertEqual(protected_after["pendingJob"]["sizeBytes"], source["size"])
        finally:
            context.close()
            browser.close()

    def test_stage57_database_v3_and_persist_fail_closed_without_lock(self):
        page = self.page
        result = page.evaluate("""async () => {
            const before = localStorage.getItem('rikuFootballLab_v3');
            state.settings.name = 'Stage57 lock guard';
            const unguarded = persist();
            const afterUnguarded = localStorage.getItem('rikuFootballLab_v3');
            const db = await openVideoDB();
            const schema = {version: db.version, stores: [...db.objectStoreNames]};
            db.close();
            const guarded = await window.withGlobalMutationLock('stage57-test-persist', () => persist());
            const afterGuarded = localStorage.getItem('rikuFootballLab_v3');
            const journalDb = await openVideoDB();
            const journalCount = await new Promise((resolve, reject) => {
                const tx = journalDb.transaction('restoreJournal', 'readonly');
                const req = tx.objectStore('restoreJournal').count();
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
            });
            journalDb.close();
            return {before, unguarded, afterUnguarded, schema, guarded,
                    afterGuarded, journalCount};
        }""")
        self.assertFalse(result["unguarded"], result)
        self.assertEqual(result["afterUnguarded"], result["before"], result)
        self.assertEqual(result["schema"]["version"], 3, result)
        self.assertIn("restoreJournal", result["schema"]["stores"], result)
        self.assertIn("restoreLocks", result["schema"]["stores"], result)
        self.assertTrue(result["guarded"], result)
        self.assertEqual(json.loads(result["afterGuarded"])["settings"]["name"], "Stage57 lock guard")
        self.assertEqual(result["journalCount"], 0, result)

    def test_stage57_committed_cleanup_verifies_chunk_sha256_and_preserves_old_generations(self):
        scenarios = [
            ("matching", """
                const key = 'stage57-c-matching';
                const originalTransaction = IDBDatabase.prototype.transaction;
                const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
                let activeChunkReadTransactions = 0, digestDuringActiveChunkRead = false;
                IDBDatabase.prototype.transaction = function(stores, mode, ...args) {
                    const names = Array.isArray(stores) ? stores : [stores];
                    const tx = originalTransaction.call(this, stores, mode, ...args);
                    if (mode === 'readonly' && names.includes('videoChunks')) {
                        activeChunkReadTransactions++;
                        let ended = false;
                        const finish = () => {
                            if (ended) return;
                            ended = true;
                            activeChunkReadTransactions--;
                        };
                        tx.addEventListener('complete', finish, {once:true});
                        tx.addEventListener('abort', finish, {once:true});
                    }
                    return tx;
                };
                Object.defineProperty(crypto.subtle, 'digest', {
                    configurable: true,
                    value: async (...args) => {
                        if (activeChunkReadTransactions > 0) digestDuringActiveChunkRead = true;
                        return originalDigest(...args);
                    }
                });
                const makeBytes = (length, seed) => {
                    const bytes = new Uint8Array(length);
                    for (let i = 0; i < length; i++) bytes[i] = (i * 31 + seed) & 255;
                    return bytes;
                };
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([bytes], {type:'video/mp4'})));
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try {
                        return await new Promise((resolve, reject) => {
                            const tx = db.transaction('videos', 'readonly');
                            let value;
                            const req = tx.objectStore('videos').get(key);
                            req.onsuccess = () => { value = req.result || null; };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = () => resolve(value);
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally { db.close(); }
                };
                const hasChunk = async prefix => {
                    const db = await openVideoDB();
                    try {
                        return await new Promise((resolve, reject) => {
                            const tx = db.transaction('videoChunks', 'readonly');
                            const req = tx.objectStore('videoChunks').count(
                                IDBKeyRange.bound(prefix, prefix + '\\uffff')
                            );
                            req.onsuccess = () => { tx.__count = req.result; };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = () => resolve(tx.__count);
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally { db.close(); }
                };
                await save(makeBytes(1024 * 1024 + 37, 1));
                const oldRecord = await readRecord();
                await save(makeBytes(2 * 1024 * 1024 + 19, 2));
                const current = await readRecord();
                return {
                    oldPrefix: oldRecord.chunkPrefix,
                    oldHashCount: oldRecord.chunkSha256?.length || 0,
                    oldChunkCount: await hasChunk(oldRecord.chunkPrefix),
                    currentPrefix: current.chunkPrefix,
                    currentHashCount: current.chunkSha256?.length || 0,
                    currentChunkCount: await hasChunk(current.chunkPrefix),
                    digestDuringActiveChunkRead,
                    journalCount: await (async () => {
                        const db = await openVideoDB();
                        try { return await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreJournal', 'readonly');
                            const req = tx.objectStore('restoreJournal').count();
                            req.onsuccess = () => { tx.__count = req.result; };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = () => resolve(tx.__count);
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                    })()
                };
            """),
            ("read-failure", """
                const key = 'stage57-c-read-failure';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([111,112,113,114]);
                const old = await readRecord();
                const originalGet = IDBObjectStore.prototype.get;
                let forcedReadFailure = false;
                IDBObjectStore.prototype.get = function(primaryKey) {
                    const request = originalGet.call(this, primaryKey);
                    if (!forcedReadFailure && this.name === 'videoChunks') {
                        forcedReadFailure = true;
                        queueMicrotask(() => { try { request.transaction.abort(); } catch (_) {} });
                    }
                    return request;
                };
                let error = null;
                try { await save([121,122,123,124]); }
                catch (caught) { error = String(caught?.message || caught); }
                finally { IDBObjectStore.prototype.get = originalGet; }
                return {
                    error, forcedReadFailure,
                    oldPrefix: old.chunkPrefix,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    activePrefix: (await readRecord())?.chunkPrefix || null,
                    safeMode: !!window.__rikuMutationSafeMode
                };
            """),
            ("corrupt", """
                const key = 'stage57-c-corrupt';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([11,12,13,14]);
                const old = await readRecord();
                const originalPut = IDBObjectStore.prototype.put;
                let corrupted = false;
                IDBObjectStore.prototype.put = function(value, primaryKey) {
                    if (!corrupted && this.name === 'videoChunks' && value instanceof Uint8Array) {
                        const copy = new Uint8Array(value);
                        copy[0] ^= 255;
                        corrupted = true;
                        return originalPut.call(this, copy, primaryKey);
                    }
                    return originalPut.call(this, value, primaryKey);
                };
                let error = null;
                try { await save([21,22,23,24]); }
                catch (caught) { error = String(caught?.message || caught); }
                finally { IDBObjectStore.prototype.put = originalPut; }
                const after = await readRecord();
                return {
                    error, corrupted,
                    oldPrefix: old.chunkPrefix,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    activePrefix: after?.chunkPrefix || null,
                    oldHashPresent: Array.isArray(old.chunkSha256)
                };
            """),
            ("legacy", """
                const key = 'stage57-c-legacy';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([31,32,33,34]);
                const old = await readRecord();
                await withGlobalMutationLock('storeClipVideo', async ctx => {
                    const db = await openVideoDB();
                    try {
                        const record = await readRecord();
                        delete record.chunkSha256;
                        ctx.videoMetadataWriteAuthorized = true;
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('videos', 'readwrite');
                            tx.objectStore('videos').put(record, key);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { ctx.videoMetadataWriteAuthorized = false; }
                    } finally { db.close(); }
                });
                const legacyHashMissing = !(await readRecord()).chunkSha256;
                let error = null;
                try { await save([41,42,43,44]); }
                catch (caught) { error = String(caught?.message || caught); }
                const after = await readRecord();
                return {
                    error,
                    oldPrefix: old.chunkPrefix,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    oldHashWasRemoved: legacyHashMissing,
                    activePrefix: after?.chunkPrefix || null,
                    activeHashCount: after?.chunkSha256?.length || 0
                };
            """),
            ("stale-generation", """
                const key = 'stage57-c-stale-generation';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([71,72,73,74]);
                const old = await readRecord();
                const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
                let digestCount = 0, generationChanged = false;
                Object.defineProperty(crypto.subtle, 'digest', {
                    configurable: true,
                    value: async (...args) => {
                        const result = await originalDigest(...args);
                        digestCount++;
                        if (digestCount === 5 && !generationChanged) {
                            generationChanged = true;
                            const ctx = window.__rikuMutationContext;
                            const db = await openVideoDB();
                            ctx.videoMetadataWriteAuthorized = true;
                            try { await new Promise((resolve, reject) => {
                                const tx = db.transaction('videos', 'readwrite');
                                const store = tx.objectStore('videos');
                                const req = store.get(key);
                                req.onsuccess = () => store.put({...req.result, chunkPrefix:key+'|tampered-generation|'}, key);
                                req.onerror = () => reject(req.error);
                                tx.oncomplete = resolve;
                                tx.onerror = () => reject(tx.error);
                                tx.onabort = () => reject(tx.error);
                            }); } finally { ctx.videoMetadataWriteAuthorized = false; db.close(); }
                        }
                        return result;
                    }
                });
                let error = null;
                try { await save([81,82,83,84]); }
                catch (caught) { error = String(caught?.message || caught); }
                finally { delete crypto.subtle.digest; }
                return {
                    error, generationChanged,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    safeMode: !!window.__rikuMutationSafeMode
                };
            """),
            ("stale-checksum", """
                const key = 'stage57-c-stale-checksum';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([91,92,93,94]);
                const old = await readRecord();
                const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
                let digestCount = 0, checksumChanged = false;
                Object.defineProperty(crypto.subtle, 'digest', {
                    configurable: true,
                    value: async (...args) => {
                        const result = await originalDigest(...args);
                        digestCount++;
                        if (digestCount === 5 && !checksumChanged) {
                            checksumChanged = true;
                            const db = await openVideoDB();
                            try { await new Promise((resolve, reject) => {
                                const tx = db.transaction('restoreJournal', 'readwrite');
                                const store = tx.objectStore('restoreJournal');
                                const req = store.getAll();
                                req.onsuccess = () => {
                                    const row = (req.result || []).find(item => item.state === 'committed');
                                    if (!row) { try { tx.abort(); } catch (_) {} return; }
                                    row.afterStateChecksum = 'stage57-tampered-checksum';
                                    store.put(row);
                                };
                                req.onerror = () => reject(req.error);
                                tx.oncomplete = resolve;
                                tx.onerror = () => reject(tx.error);
                                tx.onabort = () => reject(tx.error);
                            }); } finally { db.close(); }
                        }
                        return result;
                    }
                });
                let error = null;
                try { await save([101,102,103,104]); }
                catch (caught) { error = String(caught?.message || caught); }
                finally { delete crypto.subtle.digest; }
                return {
                    error, checksumChanged,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    safeMode: !!window.__rikuMutationSafeMode
                };
            """),
            ("stale-fence", """
                const key = 'stage57-c-stale-fence';
                const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from(bytes)], {type:'video/mp4'})));
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const countChunks = async prefix => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').count(IDBKeyRange.bound(prefix, prefix+'\\uffff'));
                        req.onsuccess = () => { tx.__count = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__count);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                await save([51,52,53,54]);
                const old = await readRecord();
                const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
                let digestCount = 0, fenceChanged = false;
                Object.defineProperty(crypto.subtle, 'digest', {
                    configurable: true,
                    value: async (...args) => {
                        const result = await originalDigest(...args);
                        digestCount++;
                        // #1 old preflight, #2 source hash, #3 staged readback, #4/#5 final old/new verification.
                        if (digestCount === 5 && !fenceChanged) {
                            fenceChanged = true;
                            const db = await openVideoDB();
                            try { await new Promise((resolve, reject) => {
                                const tx = db.transaction('restoreLocks', 'readwrite');
                                const store = tx.objectStore('restoreLocks');
                                const req = store.get('global-mutation');
                                req.onsuccess = () => {
                                    const row = req.result;
                                    store.put({...row, ownerId:'stage57-stale-owner', fenceToken:Number(row.fenceToken)+1});
                                };
                                req.onerror = () => reject(req.error);
                                tx.oncomplete = resolve;
                                tx.onerror = () => reject(tx.error);
                                tx.onabort = () => reject(tx.error);
                            }); } finally { db.close(); }
                        }
                        return result;
                    }
                });
                let error = null;
                try { await save([61,62,63,64]); }
                catch (caught) { error = String(caught?.message || caught); }
                finally { delete crypto.subtle.digest; }
                return {
                    error, fenceChanged, digestCount,
                    oldPrefix: old.chunkPrefix,
                    oldChunkCount: await countChunks(old.chunkPrefix),
                    safeMode: !!window.__rikuMutationSafeMode
                };
            """)
        ]

        def run_scenario(script):
            context = self.browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            try:
                page.goto(self.base_url, wait_until="load")
                page.wait_for_function("typeof saveClip === 'function'")
                page.wait_for_function(
                    "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
                    timeout=15000,
                )
                return page.evaluate("(script) => (async () => { " + script + " })()", script)
            finally:
                context.close()

        results = {name: run_scenario(script) for name, script in scenarios}
        matching = results["matching"]
        self.assertEqual(matching["oldChunkCount"], 0, results)
        self.assertEqual(matching["oldHashCount"], 2, results)
        self.assertEqual(matching["currentHashCount"], 3, results)
        self.assertEqual(matching["currentChunkCount"], 3, results)
        self.assertEqual(matching["journalCount"], 0, results)
        self.assertFalse(matching["digestDuringActiveChunkRead"], results)

        read_failure = results["read-failure"]
        self.assertTrue(read_failure["forcedReadFailure"], results)
        self.assertTrue(read_failure["error"], results)
        self.assertGreater(read_failure["oldChunkCount"], 0, results)
        self.assertEqual(read_failure["activePrefix"], read_failure["oldPrefix"], results)

        corrupt = results["corrupt"]
        self.assertTrue(corrupt["corrupted"], results)
        self.assertIn("SHA256", corrupt["error"] or "", results)
        self.assertGreater(corrupt["oldChunkCount"], 0, results)
        self.assertEqual(corrupt["activePrefix"], corrupt["oldPrefix"], results)

        legacy = results["legacy"]
        self.assertIsNone(legacy["error"], results)
        self.assertEqual(legacy["oldChunkCount"], 0, results)
        self.assertNotEqual(legacy["activePrefix"], legacy["oldPrefix"], results)
        self.assertEqual(legacy["activeHashCount"], 1, results)
        self.assertTrue(legacy["oldHashWasRemoved"], results)

        generation = results["stale-generation"]
        self.assertTrue(generation["generationChanged"], results)
        self.assertGreater(generation["oldChunkCount"], 0, results)
        self.assertTrue(generation["safeMode"], results)

        checksum = results["stale-checksum"]
        self.assertTrue(checksum["checksumChanged"], results)
        self.assertIn("checksum", (checksum["error"] or "").lower(), results)
        self.assertGreater(checksum["oldChunkCount"], 0, results)
        self.assertTrue(checksum["safeMode"], results)

        stale = results["stale-fence"]
        self.assertTrue(stale["fenceChanged"], results)
        self.assertGreater(stale["oldChunkCount"], 0, results)
        self.assertTrue(stale["safeMode"], results)

    def test_stage57_long_video_profiles_verify_chunks_and_preserve_old_generation_on_failures(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-d-long-video-profile';
            const chunkBytes = 1024 * 1024;
            const countPrefix = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const makeProfileBlob = (durationSeconds, bitrate, seed) => {
                const size = Math.ceil(durationSeconds * bitrate / 8);
                const parts = [];
                for (let offset = 0, index = 0; offset < size; offset += chunkBytes, index++) {
                    const length = Math.min(chunkBytes, size - offset);
                    const bytes = new Uint8Array(length);
                    bytes.fill((seed + index * 17) & 255);
                    parts.push(bytes);
                }
                return new Blob(parts, {type:'video/mp4'});
            };
            const save = blob => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, blob));
            const originalTransaction = IDBDatabase.prototype.transaction;
            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            let activeChunkReadTransactions = 0, digestInsideReadTransaction = false;
            IDBDatabase.prototype.transaction = function(stores, mode, ...args) {
                const names = Array.isArray(stores) ? stores : [stores];
                const tx = originalTransaction.call(this, stores, mode, ...args);
                if (mode === 'readonly' && names.includes('videoChunks')) {
                    activeChunkReadTransactions++;
                    let ended = false;
                    const finish = () => {
                        if (ended) return;
                        ended = true;
                        activeChunkReadTransactions--;
                    };
                    tx.addEventListener('complete', finish, {once:true});
                    tx.addEventListener('abort', finish, {once:true});
                }
                return tx;
            };
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    if (activeChunkReadTransactions > 0) digestInsideReadTransaction = true;
                    return originalDigest(...args);
                }
            });
            let profile15, profile20, current, oldCountAfterReplace, lastChunkLength, lastHashMatches;
            try {
                // Synthetic 15/20-minute profiles at a declared 256 kbit/s test bitrate.
                // These are byte-volume stress fixtures, not real camera recordings.
                profile15 = makeProfileBlob(15 * 60, 256000, 13);
                profile20 = makeProfileBlob(20 * 60, 256000, 29);
                await save(profile15);
                const first = await readRecord();
                const firstCount = Math.ceil(profile15.size / chunkBytes);
                const firstStoredCount = await countPrefix(first.chunkPrefix);
                await save(profile20);
                current = await readRecord();
                oldCountAfterReplace = await countPrefix(first.chunkPrefix);
                const expectedCount20 = Math.ceil(profile20.size / chunkBytes);
                const currentCount = await countPrefix(current.chunkPrefix);
                const lastKey = current.chunkPrefix + String(expectedCount20 - 1).padStart(8, '0');
                const db = await openVideoDB();
                try {
                    const lastBytes = await new Promise((resolve, reject) => {
                        const tx = db.transaction('videoChunks', 'readonly');
                        const req = tx.objectStore('videoChunks').get(lastKey);
                        req.onsuccess = () => { tx.__value = req.result; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__value);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    });
                    const view = lastBytes instanceof Uint8Array ? lastBytes :
                        new Uint8Array(lastBytes instanceof ArrayBuffer ? lastBytes :
                            lastBytes.buffer, lastBytes.byteOffset || 0, lastBytes.byteLength);
                    lastChunkLength = view.byteLength;
                    const digest = await originalDigest('SHA-256', view);
                    const actual = [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2,'0')).join('');
                    lastHashMatches = actual === current.chunkSha256[expectedCount20 - 1];
                } finally { db.close(); }

                // Simulate storage exhaustion while writing a replacement generation.
                const originalPut = IDBObjectStore.prototype.put;
                let quotaInjected = false, quotaError = null, quotaWrites = 0;
                IDBObjectStore.prototype.put = function(value, primaryKey) {
                    if (!quotaInjected && this.name === 'videoChunks') {
                        quotaWrites++;
                        if (quotaWrites === 2) {
                            quotaInjected = true;
                            throw new DOMException('simulated storage quota exhaustion', 'QuotaExceededError');
                        }
                    }
                    return originalPut.call(this, value, primaryKey);
                };
                try { await save(new Blob([new Uint8Array(2 * chunkBytes + 7)], {type:'video/mp4'})); }
                catch (error) { quotaError = String(error?.name || error?.message || error); }
                finally { IDBObjectStore.prototype.put = originalPut; }
                const afterQuota = await readRecord();
                const quotaOldCount = await countPrefix(current.chunkPrefix);

                // Simulate an interrupted chunk-write transaction on another replacement.
                let abortInjected = false, abortError = null;
                IDBObjectStore.prototype.put = function(value, primaryKey) {
                    const request = originalPut.call(this, value, primaryKey);
                    if (!abortInjected && this.name === 'videoChunks') {
                        abortInjected = true;
                        queueMicrotask(() => { try { this.transaction.abort(); } catch (_) {} });
                    }
                    return request;
                };
                try { await save(new Blob([new Uint8Array(chunkBytes + 11)], {type:'video/mp4'})); }
                catch (error) { abortError = String(error?.name || error?.message || error); }
                finally {
                    IDBObjectStore.prototype.put = originalPut;
                    IDBDatabase.prototype.transaction = originalTransaction;
                    delete crypto.subtle.digest;
                }
                const afterAbort = await readRecord();
                return {
                    profile15Size: profile15.size,
                    profile20Size: profile20.size,
                    profile15Chunks: firstCount,
                    profile15StoredChunks: firstStoredCount,
                    profile20Chunks: expectedCount20,
                    profile20StoredChunks: currentCount,
                    oldCountAfterReplace,
                    lastChunkLength,
                    expectedLastChunkLength: profile20.size - (expectedCount20 - 1) * chunkBytes,
                    lastHashMatches,
                    digestInsideReadTransaction,
                    quotaInjected,
                    quotaError,
                    quotaOldCount,
                    activeAfterQuota: afterQuota?.chunkPrefix || null,
                    abortInjected,
                    abortError,
                    oldCountAfterAbort: await countPrefix(current.chunkPrefix),
                    activeAfterAbort: afterAbort?.chunkPrefix || null
                };
            } finally {
                IDBObjectStore.prototype.put = IDBObjectStore.prototype.put;
                IDBDatabase.prototype.transaction = originalTransaction;
                delete crypto.subtle.digest;
            }
        }""")
        self.assertEqual(result["profile15Size"], 28_800_000, result)
        self.assertEqual(result["profile20Size"], 38_400_000, result)
        self.assertEqual(result["profile15Chunks"], 28, result)
        self.assertEqual(result["profile15StoredChunks"], 28, result)
        self.assertEqual(result["profile20Chunks"], 37, result)
        self.assertEqual(result["profile20StoredChunks"], 37, result)
        self.assertEqual(result["oldCountAfterReplace"], 0, result)
        self.assertEqual(result["lastChunkLength"], result["expectedLastChunkLength"], result)
        self.assertEqual(result["lastChunkLength"], 651_264, result)
        self.assertTrue(result["lastHashMatches"], result)
        self.assertFalse(result["digestInsideReadTransaction"], result)
        self.assertTrue(result["quotaInjected"], result)
        self.assertIn("QuotaExceededError", result["quotaError"] or "", result)
        self.assertEqual(result["activeAfterQuota"], result["activeAfterAbort"], result)
        self.assertGreater(result["quotaOldCount"], 0, result)
        self.assertTrue(result["abortInjected"], result)
        self.assertTrue(result["abortError"], result)
        self.assertGreater(result["oldCountAfterAbort"], 0, result)
        self.assertEqual(result["activeAfterAbort"], result["activeAfterQuota"], result)

    def test_stage57_interrupted_committed_cleanup_resumes_after_reload(self):
        page = self.page
        page.set_default_timeout(90000)
        page.wait_for_function("window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()", timeout=15000)
        result = page.evaluate("""async () => {
            const key = 'stage57-e-reload-recovery';
            const chunkSize = 1024 * 1024;
            const makeBlob = (size, seed) => {
                const parts = [];
                for (let offset = 0, index = 0; offset < size; offset += chunkSize, index++) {
                    const bytes = new Uint8Array(Math.min(chunkSize, size - offset));
                    bytes.fill((seed + index * 23) & 255);
                    parts.push(bytes);
                }
                return new Blob(parts, {type:'video/mp4'});
            };
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countPrefix = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countJournals = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreJournal', 'readonly');
                    const req = tx.objectStore('restoreJournal').count();
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = blob => withGlobalMutationLock('storeClipVideo', () => storeClipVideo(key, blob));
            await save(makeBlob(1_100_003, 31));
            const before = await readRecord();
            const originalTransaction = IDBDatabase.prototype.transaction;
            let cleanupAbortInjected = false, replacementError = null;
            IDBDatabase.prototype.transaction = function(stores, mode, ...args) {
                const names = Array.isArray(stores) ? stores : [stores];
                const tx = originalTransaction.call(this, stores, mode, ...args);
                if (!cleanupAbortInjected && mode === 'readwrite' &&
                    ['videos','videoChunks','restoreJournal','restoreLocks'].every(name => names.includes(name))) {
                    cleanupAbortInjected = true;
                    queueMicrotask(() => { try { tx.abort(); } catch (_) {} });
                }
                return tx;
            };
            try { await save(makeBlob(2_200_019, 47)); }
            catch (error) { replacementError = String(error?.name || error?.message || error); }
            finally { IDBDatabase.prototype.transaction = originalTransaction; }
            const interrupted = await readRecord();
            const oldChunksBeforeReload = await countPrefix(before.chunkPrefix);
            const journalsBeforeReload = await countJournals();
            const journalStatesBeforeReload = await new Promise((resolve, reject) => {
                const db = null;
                openVideoDB().then(database => {
                    const tx = database.transaction('restoreJournal', 'readonly');
                    const req = tx.objectStore('restoreJournal').getAll();
                    req.onsuccess = () => { tx.__states = (req.result || []).map(row => row.state); };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => { database.close(); resolve(tx.__states); };
                    tx.onerror = () => { database.close(); reject(tx.error); };
                    tx.onabort = () => { database.close(); reject(tx.error); };
                }).catch(reject);
            });
            const safeModeBeforeReload = !!window.__rikuMutationSafeMode;
            return {
                oldPrefix: before.chunkPrefix,
                newPrefix: interrupted?.chunkPrefix || null,
                activePrefixBeforeReload: interrupted?.chunkPrefix || null,
                cleanupAbortInjected,
                replacementError,
                oldChunksBeforeReload,
                journalsBeforeReload,
                journalStatesBeforeReload,
                safeModeBeforeReload,
                cleanupDiagnostic: window.__rikuStage57CleanupDiagnostic || null
            };
        }""")
        self.assertTrue(result["cleanupAbortInjected"], result)
        self.assertTrue(result["replacementError"], result)
        self.assertNotEqual(result["activePrefixBeforeReload"], result["oldPrefix"], result)
        self.assertGreater(result["oldChunksBeforeReload"], 0, result)
        self.assertGreater(result["journalsBeforeReload"], 0, result)
        self.assertEqual(result["journalStatesBeforeReload"], ["committed"], result)
        self.assertTrue(result["safeModeBeforeReload"], result)

        page.reload(wait_until="load")
        page.wait_for_function(
            "!!(window.__rikuMutationSafeMode || (window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()))",
            timeout=30000,
        )
        recovered = page.evaluate("""async prefixes => {
            const oldPrefix = prefixes.oldPrefix;
            const newPrefix = prefixes.newPrefix;
            const key = 'stage57-e-reload-recovery';
            const db = await openVideoDB();
            try {
                const read = (store, requestFactory) => new Promise((resolve, reject) => {
                    const tx = db.transaction(store, 'readonly');
                    const req = requestFactory(tx.objectStore(store));
                    req.onsuccess = () => { tx.__value = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__value);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
                const record = await read('videos', store => store.get(key));
                const journals = await read('restoreJournal', store => store.getAll());
                const countPrefix = prefix => new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
                const oldCount = await countPrefix(oldPrefix);
                const newCount = await countPrefix(newPrefix);
                return {
                    activePrefix: record?.chunkPrefix || null,
                    activeChunkCount: record?.chunkCount || 0,
                    hashCount: record?.chunkSha256?.length || 0,
                    journals: journals.length,
                    oldCount,
                    newCount,
                    safeMode: !!window.__rikuMutationSafeMode,
                    recoveryReady: !!window.__rikuMutationRecoveryReady?.(),
                    notice: document.getElementById("recordSaveNotice")?.textContent || "",
                    journalStates: journals.map(row => ({state: row.state, reason: row.reason, before: row.beforeStateChecksum, after: row.afterStateChecksum}))
                };
            } finally { db.close(); }
        }""", {"oldPrefix": result["oldPrefix"], "newPrefix": result["newPrefix"]})
        self.assertGreater(recovered["activeChunkCount"], 0, recovered)
        self.assertEqual(recovered["hashCount"], recovered["activeChunkCount"], recovered)
        self.assertEqual(recovered["activePrefix"], result["newPrefix"], recovered)
        self.assertEqual(recovered["journals"], 0, recovered)
        self.assertEqual(recovered["oldCount"], 0, recovered)
        self.assertGreater(recovered["newCount"], 0, recovered)
        self.assertFalse(recovered["safeMode"], recovered)
        self.assertTrue(recovered["recoveryReady"], recovered)

    def test_stage57_recovery_required_stops_all_later_journal_cleanup(self):
        source = (ROOT / "riku-global-mutation-lock.js").read_text(encoding="utf-8")
        start = source.index("async function runRecovery()")
        end = source.index("window.withGlobalMutationLock", start)
        recovery = source[start:end]
        recovery_required_preflight = recovery.index('const blockedJournal = journals.find(journal => journal.state === "recovery-required")')
        journal_loop = recovery.index("for (const journal of journals)")
        recovery_required_throw = recovery.index('throw new Error("recovery-requiredの未解決ジャーナルが残っています。後続の復旧・動画削除を停止しました")')
        first_cleanup = recovery.index("await finishCommittedJournal(ctx, journal)")
        self.assertLess(recovery_required_preflight, journal_loop)
        self.assertLess(recovery_required_preflight, first_cleanup)
        self.assertLess(recovery_required_preflight, recovery_required_throw)
        self.assertIn("window.__rikuMutationSafeMode = true", recovery[recovery_required_preflight:recovery_required_throw])
        unresolved = recovery.index('reason: "localStorage matches neither before nor confirmed after snapshot"')
        stop = recovery.index('throw new Error("復旧ジャーナルがbefore/afterのどちらとも一致しません。後続の動画削除を停止しました")', unresolved)
        self.assertLess(unresolved, stop)
        self.assertIn('state: "recovery-required"', recovery)
        self.assertIn("window.__rikuMutationSafeMode = true", recovery[unresolved:stop])
        self.assertIn("for (const journal of journals)", recovery)
        self.assertIn("await finishCommittedJournal(ctx, journal)", recovery)
        self.assertIn("async function finishCommittedJournal", source)
        self.assertIn('const recoveryOwner = ctx.operation === "startup-recovery";', source)
        self.assertIn("row.ownerId = ctx.ownerId", source)
        self.assertIn("row.fenceToken = ctx.fenceToken", source)
        self.assertIn('await updateJournal(ctx, { state: "committed" }, journal.restoreId);', recovery)
        finish_start = source.index("async function finishCommittedJournal")
        finish_end = source.index("async function releaseFence", finish_start)
        cleanup = source[finish_start:finish_end]
        self.assertIn("await verifyPrefix(prefix, expectedRecord)", cleanup)
        self.assertIn("latestJournal.journalChecksum !== journalDigest(latestJournal)", cleanup)
        self.assertIn("Number(latestLock.leaseUntil) <= Date.now()", cleanup)
        self.assertIn("JSON.stringify(videoRecordSummary(latest)) !== JSON.stringify(videoRecordSummary(previous))", cleanup)
        self.assertIn("ctx.chunkDeleteAuthorized = true", cleanup)
        self.assertIn("tx.objectStore(\"restoreJournal\").delete(latestJournal.restoreId)", cleanup)

    def test_stage57_pending_match_job_requires_persisted_analysis_before_clear(self):
        page = self.page
        result = page.evaluate("""async () => {
            await savePendingMatchJob({jobId: 'stage57-pending', createdAt: Date.now()});
            let blocked = false;
            try { await clearPendingMatchJob(); }
            catch (error) { blocked = /永続保存を確認できない/.test(error.message); }
            const retained = await getPendingMatchJob();
            state.matchAnalyses = [{id: 'stage57-analysis', jobId: 'stage57-pending'}];
            const persisted = await window.withGlobalMutationLock('stage57-persist-analysis', () => persist());
            await clearPendingMatchJob();
            const afterClear = await getPendingMatchJob();
            return {blocked, retainedJobId: retained?.jobId || null, persisted, afterClear};
        }""")
        self.assertTrue(result["blocked"], result)
        self.assertEqual(result["retainedJobId"], "stage57-pending", result)
        self.assertTrue(result["persisted"], result)
        self.assertIsNone(result["afterClear"], result)

    def test_stage57_global_mutation_lock_serializes_two_tabs(self):
        page = self.page
        second = page.context.new_page()
        try:
            second.goto(self.base_url, wait_until="load")
            page.wait_for_function("window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()")
            second.wait_for_function("window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()")
            page.evaluate("""() => {
                window.__stage57LockEntered = false;
                window.__startStage57Hold = () => {
                    window.__stage57HoldPromise = window.withGlobalMutationLock('stage57-hold', async () => {
                        window.__stage57LockEntered = true;
                        await new Promise(resolve => { window.__releaseStage57Hold = resolve; });
                    });
                };
                window.__startStage57Hold();
            }""")
            page.wait_for_function("window.__stage57LockEntered === true")
            second.evaluate("""() => {
                window.__stage57SecondFinished = false;
                window.__stage57SecondPromise = window.withGlobalMutationLock('stage57-second', async () => {
                    window.__stage57SecondFinished = true;
                }).catch(error => { window.__stage57SecondError = String(error); });
            }""")
            second.wait_for_function("!!window.__stage57SecondError")
            self.assertFalse(second.evaluate("window.__stage57SecondFinished"))
            self.assertIn("別のタブで保存処理中", second.evaluate("window.__stage57SecondError"))
            page.evaluate("window.__releaseStage57Hold()")
            # Wait for finalization and navigator.locks release before retrying in tab two.
            page.evaluate("window.__stage57HoldPromise")
            second.evaluate("""() => {
                window.__stage57SecondError = null;
                window.__stage57SecondFinished = false;
                window.__stage57SecondPromise = window.withGlobalMutationLock('stage57-second-retry', async () => {
                    window.__stage57SecondFinished = true;
                }).catch(error => { window.__stage57SecondError = String(error); });
            }""")
            second.wait_for_function(
                "window.__stage57SecondFinished === true || !!window.__stage57SecondError",
                timeout=15000,
            )
            self.assertTrue(
                second.evaluate("window.__stage57SecondFinished"),
                second.evaluate("window.__stage57SecondError || null") or "lock retry timed out",
            )
            self.assertIsNone(second.evaluate("window.__stage57SecondError || null"))
        finally:
            try:
                page.evaluate("window.__releaseStage57Hold && window.__releaseStage57Hold()")
            except Exception:
                pass
            second.close()



    def _stage57_v1_checksum(self, text):
        encoded = text.encode("utf-16-le", "surrogatepass")
        units = [
            encoded[i] | (encoded[i + 1] << 8)
            for i in range(0, len(encoded), 2)
        ]
        a = 0x811C9DC5
        b = 0x9E3779B9
        for i, code_unit in enumerate(units):
            a = ((a ^ code_unit) * 0x01000193) & 0xFFFFFFFF
            b = ((b ^ (code_unit + i)) * 0x85EBCA6B) & 0xFFFFFFFF

        def base36(number):
            digits = "0123456789abcdefghijklmnopqrstuvwxyz"
            if number == 0:
                return "0"
            result = ""
            while number:
                number, remainder = divmod(number, 36)
                result = digits[remainder] + result
            return result

        return f"{base36(len(units))}-{a:08x}{b:08x}"

    def test_stage57_journal_digest_matches_independent_v1_checksum(self):
        result = self.page.evaluate("""async () => {
            const binaryInfo = async value => {
                if (value == null) return null;
                let bytes;
                let kind;
                if (value instanceof Blob) {
                    bytes = await value.arrayBuffer();
                    kind = "Blob";
                } else if (value instanceof ArrayBuffer) {
                    bytes = value;
                    kind = "ArrayBuffer";
                } else if (ArrayBuffer.isView(value)) {
                    bytes = value.buffer.slice(
                        value.byteOffset,
                        value.byteOffset + value.byteLength
                    );
                    kind = value.constructor?.name || "ArrayBufferView";
                } else {
                    return {kind: "json", value: JSON.stringify(value)};
                }
                const digest = await crypto.subtle.digest("SHA-256", bytes);
                return {
                    kind,
                    byteLength: bytes.byteLength,
                    sha256: [...new Uint8Array(digest)]
                        .map(value => value.toString(16).padStart(2, "0"))
                        .join("")
                };
            };

            const summarizeVideoRecordForSnapshot = async record => {
                if (!record) return null;
                const metadata = {};
                for (const key of Object.keys(record).sort()) {
                    if (key === "blob" || key === "blobData") continue;
                    metadata[key] = record[key];
                }
                return {
                    metadata,
                    blob: await binaryInfo(record.blob),
                    blobData: await binaryInfo(record.blobData)
                };
            };

            const snapshot = async () => {
                const db = await openVideoDB();
                try {
                    const raw = await new Promise((resolve, reject) => {
                        const tx = db.transaction(
                            ["restoreJournal", "videos", "videoChunks"],
                            "readonly"
                        );
                        const values = {};
                        const requests = [
                            ["journalCount", tx.objectStore("restoreJournal").count()],
                            ["videoKeys", tx.objectStore("videos").getAllKeys()],
                            ["videoRecords", tx.objectStore("videos").getAll()],
                            ["chunkKeys", tx.objectStore("videoChunks").getAllKeys()],
                            ["chunkRecords", tx.objectStore("videoChunks").getAll()]
                        ];
                        for (const [name, request] of requests) {
                            request.onsuccess = () => { values[name] = request.result; };
                            request.onerror = () => reject(
                                request.error || new Error("snapshot request failed: " + name)
                            );
                        }
                        tx.oncomplete = () => resolve(values);
                        tx.onerror = () => reject(
                            tx.error || new Error("snapshot transaction failed")
                        );
                        tx.onabort = () => reject(
                            tx.error || new Error("snapshot transaction aborted")
                        );
                    });

                    const videos = await Promise.all(
                        raw.videoRecords.map(async (record, index) => ({
                            key: String(raw.videoKeys[index]),
                            value: await summarizeVideoRecordForSnapshot(record)
                        }))
                    );
                    const chunks = await Promise.all(
                        raw.chunkRecords.map(async (record, index) => ({
                            key: String(raw.chunkKeys[index]),
                            value: await binaryInfo(record)
                        }))
                    );
                    return {
                        journalCount: raw.journalCount,
                        videos,
                        chunks,
                        appState: localStorage.getItem("rikuFootballLab_v3")
                    };
                } finally {
                    db.close();
                }
            };

            const blob = new Blob(
                [Uint8Array.from([0, 1, 2, 255])],
                {type: "video/mp4"}
            );
            const arrayBuffer = Uint8Array.from([10, 11, 12]).buffer;
            const typedArray = Uint8Array.from([21, 22, 23, 24]);

            const chunkedA = {
                storageFormat: "chunks",
                chunkPrefix: "stage57-b-chunked|generation-a|",
                chunkCount: 2,
                size: 7,
                name: "stage57-a.mp4",
                type: "video/mp4",
                blobType: "video/mp4",
                lastModified: 1700000000000,
                blob: null,
                blobData: null
            };
            const chunkedB = {
                ...chunkedA,
                chunkPrefix: "stage57-b-chunked|generation-b|",
                chunkCount: 3,
                size: 9,
                name: "stage57-b.mp4"
            };

            const changes = [
                {
                    key: "stage57-b-blob", kind: "replace",
                    oldPrefix: null, newPrefix: null,
                    oldRecord: null,
                    newRecord: {
                        storageFormat: "blob",
                        name: "stage57-blob-⚽-陸玖.mp4",
                        type: "video/mp4",
                        blobType: "video/mp4",
                        lastModified: 1700000000000,
                        size: 4,
                        blob,
                        blobData: null
                    }
                },
                {
                    key: "stage57-b-arraybuffer", kind: "replace",
                    oldPrefix: null, newPrefix: null,
                    oldRecord: null,
                    newRecord: {
                        storageFormat: "arraybuffer",
                        name: "stage57-arraybuffer.mp4",
                        type: "video/mp4",
                        blobType: "video/mp4",
                        lastModified: 1700000000001,
                        size: 3,
                        blob: null,
                        blobData: arrayBuffer
                    }
                },
                {
                    key: "stage57-b-view", kind: "replace",
                    oldPrefix: null, newPrefix: null,
                    oldRecord: null,
                    newRecord: {
                        storageFormat: "arraybuffer",
                        name: "stage57-view.mp4",
                        type: "video/mp4",
                        blobType: "video/mp4",
                        lastModified: 1700000000002,
                        size: 4,
                        blob: null,
                        blobData: typedArray
                    }
                },
                {
                    key: "stage57-b-chunked", kind: "replace",
                    oldPrefix: null, newPrefix: null,
                    oldRecord: null,
                    newRecord: chunkedA
                },
                {
                    key: "stage57-b-chunked", kind: "replace",
                    oldPrefix: null, newPrefix: null,
                    oldRecord: chunkedA,
                    newRecord: chunkedB
                }
            ];

            function videoRecordSummary(record) {
                if (!record) return null;
                const blobData = record.blobData;
                return {
                    storageFormat: record.storageFormat || null,
                    chunkPrefix: record.chunkPrefix || null,
                    chunkCount: Number(record.chunkCount) || null,
                    size: Number(record.size) ||
                        (record.blob instanceof Blob ? record.blob.size : null),
                    name: record.name || null,
                    type: record.type || null,
                    blobType: record.blobType || null,
                    lastModified: Number(record.lastModified) || 0,
                    blobSize: record.blob instanceof Blob
                        ? record.blob.size : null,
                    blobDataBytes: blobData instanceof ArrayBuffer
                        ? blobData.byteLength
                        : (ArrayBuffer.isView(blobData)
                            ? blobData.byteLength : null)
                };
            }

            function canonicalJournal(row) {
                return {
                    restoreId: row.restoreId,
                    operationId: row.operationId,
                    ownerId: row.ownerId,
                    fenceToken: Number(row.fenceToken),
                    operation: row.operation,
                    state: row.state,
                    beforeStateChecksum: row.beforeStateChecksum,
                    beforeStateLength: row.beforeStateLength,
                    afterStateChecksum: row.afterStateChecksum,
                    afterStateLength: row.afterStateLength,
                    videoChanges: (row.videoChanges || []).map(change => ({
                        key: String(change.key),
                        kind: change.kind || null,
                        oldPrefix: change.oldPrefix || null,
                        newPrefix: change.newPrefix || null,
                        oldRecord: videoRecordSummary(change.oldRecord),
                        newRecord: videoRecordSummary(change.newRecord)
                    }))
                };
            }

            const before = await snapshot();
            const captured = await window.withGlobalMutationLock(
                "stage57-test-b-digest",
                async () => {
                    for (const change of changes) {
                        await window.__rikuRecordVideoChange(change);
                    }

                    const db = await openVideoDB();
                    try {
                        return await new Promise((resolve, reject) => {
                            const tx = db.transaction("restoreJournal", "readonly");
                            let row;
                            const request = tx.objectStore("restoreJournal")
                                .get(window.__rikuMutationContext.restoreId);
                            request.onsuccess = () => { row = request.result; };
                            request.onerror = () => reject(
                                request.error || new Error("journal read failed")
                            );
                            tx.oncomplete = () => {
                                if (!row) {
                                    reject(new Error("Stage57 journal row missing"));
                                    return;
                                }
                                const canonical = canonicalJournal(row);
                                resolve({
                                    state: row.state,
                                    journalChecksum: row.journalChecksum,
                                    canonicalJson: JSON.stringify(canonical),
                                    changeCount: row.videoChanges.length,
                                    keys: row.videoChanges.map(change => String(change.key))
                                });
                            };
                            tx.onerror = () => reject(
                                tx.error || new Error("journal transaction failed")
                            );
                            tx.onabort = () => reject(
                                tx.error || new Error("journal transaction aborted")
                            );
                        });
                    } finally {
                        db.close();
                    }
                }
            );
            const after = await snapshot();
            return {before, captured, after};
        }""");

        captured = result["captured"]
        canonical = json.loads(captured["canonicalJson"])

        self.assertEqual(captured["state"], "prepared", result)
        self.assertEqual(captured["changeCount"], 5, result)
        self.assertEqual(
            captured["keys"],
            [
                "stage57-b-blob",
                "stage57-b-arraybuffer",
                "stage57-b-view",
                "stage57-b-chunked",
                "stage57-b-chunked",
            ],
            result,
        )
        self.assertEqual(
            list(canonical.keys()),
            [
                "restoreId",
                "operationId",
                "ownerId",
                "fenceToken",
                "operation",
                "state",
                "beforeStateChecksum",
                "beforeStateLength",
                "afterStateChecksum",
                "afterStateLength",
                "videoChanges",
            ],
            result,
        )
        self.assertEqual(
            list(canonical["videoChanges"][0]["newRecord"].keys()),
            [
                "storageFormat",
                "chunkPrefix",
                "chunkCount",
                "size",
                "name",
                "type",
                "blobType",
                "lastModified",
                "blobSize",
                "blobDataBytes",
            ],
            result,
        )
        self.assertEqual(canonical["videoChanges"][0]["newRecord"]["blobSize"], 4, result)
        self.assertEqual(canonical["videoChanges"][0]["newRecord"]["name"], "stage57-blob-⚽-陸玖.mp4", result)
        self.assertEqual(canonical["videoChanges"][1]["newRecord"]["blobDataBytes"], 3, result)
        self.assertEqual(canonical["videoChanges"][2]["newRecord"]["blobDataBytes"], 4, result)
        self.assertEqual(canonical["videoChanges"][3]["newRecord"]["chunkCount"], 2, result)
        self.assertEqual(canonical["videoChanges"][4]["newRecord"]["chunkCount"], 3, result)
        self.assertEqual(
            canonical["videoChanges"][3]["newRecord"],
            canonical["videoChanges"][4]["oldRecord"],
            result,
        )
        self.assertEqual(
            captured["journalChecksum"],
            self._stage57_v1_checksum(captured["canonicalJson"]),
            result,
        )

        self.assertEqual(result["after"]["journalCount"], result["before"]["journalCount"], result)
        self.assertEqual(result["after"]["videos"], result["before"]["videos"], result)
        self.assertEqual(result["after"]["chunks"], result["before"]["chunks"], result)
        self.assertEqual(result["after"]["appState"], result["before"]["appState"], result)
        self.assertEqual(result["after"]["journalCount"], 0, result)


    def test_stage57_cancel_video_change_rejects_corrupt_journal_before_chunk_cleanup(self):
        page = self.page
        page.wait_for_function("typeof window.__rikuCancelVideoChange === 'function'")
        result = page.evaluate("""async () => {
            const key = 'stage57-cancel-corrupt';
            const prefix = key + '|generation|';
            window.__stage57CancelDiag = null;
            try {
                await withGlobalMutationLock('stage57-cancel-corrupt', async () => {
                    await window.__rikuRecordVideoChange({
                        key, kind:'replace', oldPrefix:null, newPrefix:prefix,
                        oldRecord:null,
                        newRecord:{storageFormat:'chunked-v1',chunkPrefix:prefix,chunkCount:1,size:4}
                    });
                    const db = await openVideoDB();
                    let tamperedChecksum, beforeChanges;
                    try {
                        await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreJournal', 'readwrite');
                            const store = tx.objectStore('restoreJournal');
                            const req = store.get(window.__rikuMutationContext.restoreId);
                            req.onsuccess = () => {
                                const row = req.result;
                                row.beforeStateChecksum = 'tampered-before-checksum';
                                tamperedChecksum = row.journalChecksum;
                                beforeChanges = row.videoChanges.length;
                                store.put(row);
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally { db.close(); }
                    let cancelError = null;
                    try { await window.__rikuCancelVideoChange(prefix); }
                    catch (error) { cancelError = String(error?.message || error); }
                    const checkDb = await openVideoDB();
                    let after;
                    try {
                        after = await new Promise((resolve, reject) => {
                            const tx = checkDb.transaction('restoreJournal', 'readonly');
                            const req = tx.objectStore('restoreJournal')
                                .get(window.__rikuMutationContext.restoreId);
                            req.onsuccess = () => { tx.__row = req.result; };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = () => resolve(tx.__row);
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally { checkDb.close(); }
                    window.__stage57CancelDiag = {
                        cancelError,
                        tamperedChecksum,
                        afterChecksum:after?.journalChecksum || null,
                        beforeChanges,
                        afterChanges:after?.videoChanges?.length || 0,
                        retainedPrefix:after?.videoChanges?.[0]?.newPrefix || null,
                        safeMode:!!window.__rikuMutationSafeMode
                    };
                });
            } catch (_) {}
            return window.__stage57CancelDiag;
        }""");
        self.assertIsNotNone(result, result)
        self.assertTrue(result["cancelError"], result)
        self.assertEqual(result["afterChecksum"], result["tamperedChecksum"], result)
        self.assertEqual(result["afterChanges"], result["beforeChanges"], result)
        self.assertEqual(result["retainedPrefix"], "stage57-cancel-corrupt|generation|", result)
        self.assertTrue(result["safeMode"], result)

        source = (ROOT / "index.html").read_text(encoding="utf-8")
        start = source.index("async function storeClipVideo")
        end = source.index("\nasync function ", start + 30)
        catch = source[start:end]
        self.assertLess(
            catch.index("await window.__rikuCancelVideoChange(chunkPrefix)"),
            catch.index("await deleteChunks(chunkPrefix)"),
        )

    def test_stage57_legacy_chunk_hash_migration_rechecks_authority_and_generation(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const makeBytes = values => Uint8Array.from(values);
            const readRecord = async key => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const writeRecord = async (key, record) => {
                const ctx = window.__rikuMutationContext;
                if (ctx) ctx.videoMetadataWriteAuthorized = true;
                const db = await openVideoDB();
                try { await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readwrite');
                    tx.objectStore('videos').put(record, key);
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally {
                    db.close();
                    if (ctx) ctx.videoMetadataWriteAuthorized = false;
                }
            };
            const makeLegacy = async (key, bytes) => {
                await withGlobalMutationLock('storeClipVideo', async () => {
                    await storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}));
                });
                const record = await readRecord(key);
                if (!record) throw new Error('legacy fixture seed did not persist a video record: ' + key);
                const {chunkSha256, ...legacy} = record;
                await withGlobalMutationLock('storeClipVideo', async ctx => {
                    ctx.videoMetadataWriteAuthorized = true;
                    try { await writeRecord(key, legacy); }
                    finally { ctx.videoMetadataWriteAuthorized = false; }
                });
                return record;
            };
            const saveReplacement = (key, bytes) => withGlobalMutationLock(
                'storeClipVideo', () => storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            const successKey = 'stage57-legacy-success';
            const successBytes = makeBytes([1,2,3,4,5,6,7]);
            const oldSuccess = await makeLegacy(successKey, successBytes);
            let capturedOldHashes = null;
            const originalRecordChange = window.__rikuRecordVideoChange;
            window.__rikuRecordVideoChange = async change => {
                if (change.key === successKey) capturedOldHashes = change.oldRecord?.chunkSha256 || null;
                return originalRecordChange(change);
            };
            await saveReplacement(successKey, makeBytes([8,9,10,11,12]));
            window.__rikuRecordVideoChange = originalRecordChange;
            const successCurrent = await readRecord(successKey);
            const expectedDigest = await crypto.subtle.digest('SHA-256', successBytes);
            const expectedHash = [...new Uint8Array(expectedDigest)].map(v => v.toString(16).padStart(2,'0')).join('');
            const success = {
                capturedOldHashes,
                expectedHash,
                oldPrefix:oldSuccess.chunkPrefix,
                oldChunkCount:await countChunks(oldSuccess.chunkPrefix),
                activePrefix:successCurrent?.chunkPrefix || null,
                activeHashCount:successCurrent?.chunkSha256?.length || 0
            };

            const readKey = 'stage57-legacy-read-failure';
            const oldRead = await makeLegacy(readKey, makeBytes([21,22,23,24]));
            const originalGet = IDBObjectStore.prototype.get;
            let readAbortInjected = false, readError = null;
            IDBObjectStore.prototype.get = function(primaryKey) {
                const request = originalGet.call(this, primaryKey);
                if (!readAbortInjected && this.name === 'videoChunks') {
                    readAbortInjected = true;
                    queueMicrotask(() => { try { request.transaction.abort(); } catch (_) {} });
                }
                return request;
            };
            try { await saveReplacement(readKey, makeBytes([25,26,27,28])); }
            catch (error) { readError = String(error?.message || error); }
            finally { IDBObjectStore.prototype.get = originalGet; }
            const afterRead = await readRecord(readKey);
            const readFailure = {
                readAbortInjected, readError, oldPrefix:oldRead.chunkPrefix,
                oldChunkCount:await countChunks(oldRead.chunkPrefix),
                activePrefix:afterRead?.chunkPrefix || null,
                hashStillMissing:!Array.isArray(afterRead?.chunkSha256)
            };

            const generationKey = 'stage57-legacy-generation';
            const oldGeneration = await makeLegacy(generationKey, makeBytes([31,32,33,34]));
            const originalDigestMethod = crypto.subtle.digest.bind(crypto.subtle);
            let generationChanged = false, generationError = null, generationDigestCalls = 0;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable:true,
                value:async (...args) => {
                    const digest = await originalDigestMethod(...args);
                    generationDigestCalls++;
                    if (!generationChanged && generationDigestCalls === 2) {
                        generationChanged = true;
                        const latest = await readRecord(generationKey);
                        await writeRecord(generationKey, {...latest,name:'generation-tampered'});
                    }
                    return digest;
                }
            });
            try { await saveReplacement(generationKey, makeBytes([35,36,37,38])); }
            catch (error) { generationError = String(error?.message || error); }
            finally { delete crypto.subtle.digest; }
            const afterGeneration = await readRecord(generationKey);
            const generation = {
                generationChanged, generationError, oldPrefix:oldGeneration.chunkPrefix,
                oldChunkCount:await countChunks(oldGeneration.chunkPrefix),
                activePrefix:afterGeneration?.chunkPrefix || null,
                hashStillMissing:!Array.isArray(afterGeneration?.chunkSha256),
                safeMode:!!window.__rikuMutationSafeMode
            };
            // The fixture deliberately changed metadata; reset only the safety latch after assertions.
            window.__rikuMutationSafeMode = false;

            return {success,readFailure,generation};
        }""");
        self.assertEqual(result["success"]["capturedOldHashes"], [result["success"]["expectedHash"]], result)
        self.assertEqual(result["success"]["oldChunkCount"], 0, result)
        self.assertNotEqual(result["success"]["activePrefix"], result["success"]["oldPrefix"], result)
        self.assertEqual(result["success"]["activeHashCount"], 1, result)

        read_failure = result["readFailure"]
        self.assertTrue(read_failure["readAbortInjected"], result)
        self.assertTrue(read_failure["readError"], result)
        self.assertGreater(read_failure["oldChunkCount"], 0, result)
        self.assertEqual(read_failure["activePrefix"], read_failure["oldPrefix"], result)
        self.assertTrue(read_failure["hashStillMissing"], result)

        generation = result["generation"]
        self.assertTrue(generation["generationChanged"], result)
        self.assertTrue(generation["generationError"], result)
        self.assertGreater(generation["oldChunkCount"], 0, result)
        self.assertEqual(generation["activePrefix"], generation["oldPrefix"], result)
        self.assertTrue(generation["hashStillMissing"], result)
        self.assertTrue(generation["safeMode"], result)

        source = (ROOT / "index.html").read_text(encoding="utf-8")
        helper_start = source.index("async function verifyChunkedVideoGeneration")
        helper_end = source.index("async function storeClipVideo", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("db.transaction(['videos','restoreLocks'],'readwrite')", helper)
        self.assertIn("latestLock.ownerId!==ctx.ownerId", helper)
        self.assertIn("Number(latestLock.fenceToken)!==Number(ctx.fenceToken)", helper)
        self.assertIn("String(latestVideo.chunkPrefix||'')!==prefix", helper)
        self.assertLess(
            helper.index("crypto.subtle.digest('SHA-256',bytes)"),
            helper.index("db.transaction(['videos','restoreLocks'],'readwrite')"),
        )


    def test_stage57_legacy_chunk_hash_migration_stops_on_fence_change(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-fence-migration';
            const oldBytes = Uint8Array.from([41,42,43,44,45,46]);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readLock = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreLocks', 'readonly');
                    const req = tx.objectStore('restoreLocks').get('global-mutation');
                    req.onsuccess = () => { tx.__row = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__row);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + '00000000');
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy fence fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await new Promise((resolve, reject) => {
                    const db = null;
                    const txdb = openVideoDB();
                    txdb.then(database => {
                        const tx = database.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacyRecord, key);
                        tx.oncomplete = () => { database.close(); resolve(); };
                        tx.onerror = () => { database.close(); reject(tx.error); };
                        tx.onabort = () => { database.close(); reject(tx.error); };
                    }, reject);
                }); } finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBefore = await readChunk(seeded.chunkPrefix);
            const oldChunkCountBefore = await countChunks(seeded.chunkPrefix);
            if (Array.isArray(legacyBefore?.chunkSha256)) {
                throw new Error('fixture did not create a legacy record without chunkSha256');
            }

            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
            let digestCalls = 0, fenceChanged = false, changedLock = null, migrationError = null;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    const digest = await originalDigest(...args);
                    digestCalls++;
                    // #1 hashes the replacement input; #2 hashes the legacy video chunk.
                    if (digestCalls === 2 && !fenceChanged) {
                        const current = await readLock();
                        if (!current) throw new Error('global mutation lock row disappeared during fixture');
                        const db = await openVideoDB();
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreLocks', 'readwrite');
                            const store = tx.objectStore('restoreLocks');
                            const req = store.get('global-mutation');
                            req.onsuccess = () => {
                                const row = req.result;
                                store.put({
                                    ...row,
                                    ownerId: 'stage57-stale-legacy-owner',
                                    fenceToken: Number(row.fenceToken) + 1
                                });
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                        changedLock = await readLock();
                        fenceChanged = !!changedLock &&
                            changedLock.ownerId === 'stage57-stale-legacy-owner' &&
                            Number(changedLock.fenceToken) === Number(current.fenceToken) + 1;
                    }
                    return digest;
                }
            });
            try {
                await save(Uint8Array.from([51,52,53,54,55]));
            } catch (error) {
                migrationError = String(error?.message || error);
            } finally {
                if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                else delete crypto.subtle.digest;
            }

            const after = await readRecord();
            const oldChunkAfter = await readChunk(seeded.chunkPrefix);
            return {
                digestCalls, fenceChanged, migrationError,
                oldRecordUnchanged: JSON.stringify(after) === JSON.stringify(legacyBefore),
                oldPrefixBefore: seeded.chunkPrefix,
                oldPrefixAfter: after?.chunkPrefix || null,
                oldChunkCountBefore,
                oldChunkCountAfter: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(oldChunkAfter) === JSON.stringify(oldChunkBefore),
                hashStillMissing: !Array.isArray(after?.chunkSha256),
                safeMode: !!window.__rikuMutationSafeMode
            };
        }""")
        self.assertTrue(result["fenceChanged"], result)
        self.assertGreaterEqual(result["digestCalls"], 2, result)
        self.assertTrue(result["migrationError"], result)
        self.assertTrue(result["oldRecordUnchanged"], result)
        self.assertEqual(result["oldPrefixAfter"], result["oldPrefixBefore"], result)
        self.assertGreater(result["oldChunkCountBefore"], 0, result)
        self.assertEqual(result["oldChunkCountAfter"], result["oldChunkCountBefore"], result)
        self.assertTrue(result["oldChunkBytesUnchanged"], result)
        self.assertTrue(result["hashStillMissing"], result)
        self.assertTrue(result["safeMode"], result)


    def test_stage57_legacy_chunk_hash_migration_stops_on_owner_change(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-owner-migration';
            const oldBytes = Uint8Array.from([41,42,43,44,45,46]);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readLock = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreLocks', 'readonly');
                    const req = tx.objectStore('restoreLocks').get('global-mutation');
                    req.onsuccess = () => { tx.__row = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__row);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + '00000000');
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy fence fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await new Promise((resolve, reject) => {
                    const txdb = openVideoDB();
                    txdb.then(database => {
                        const tx = database.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacyRecord, key);
                        tx.oncomplete = () => { database.close(); resolve(); };
                        tx.onerror = () => { database.close(); reject(tx.error); };
                        tx.onabort = () => { database.close(); reject(tx.error); };
                    }, reject);
                }); } finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBefore = await readChunk(seeded.chunkPrefix);
            const oldChunkCountBefore = await countChunks(seeded.chunkPrefix);
            if (Array.isArray(legacyBefore?.chunkSha256)) {
                throw new Error('fixture did not create a legacy record without chunkSha256');
            }

            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
            let digestCalls = 0, ownerChanged = false, changedLock = null, migrationError = null;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    const digest = await originalDigest(...args);
                    digestCalls++;
                    // #1 hashes the replacement input; #2 hashes the legacy video chunk.
                    if (digestCalls === 2 && !ownerChanged) {
                        const current = await readLock();
                        if (!current) throw new Error('global mutation lock row disappeared during fixture');
                        const db = await openVideoDB();
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreLocks', 'readwrite');
                            const store = tx.objectStore('restoreLocks');
                            const req = store.get('global-mutation');
                            req.onsuccess = () => {
                                const row = req.result;
                                store.put({
                                    ...row,
                                    ownerId: 'stage57-stale-legacy-owner'
                                });
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                        changedLock = await readLock();
                        ownerChanged = !!changedLock &&
                            changedLock.ownerId === 'stage57-stale-legacy-owner' &&
                            Number(changedLock.fenceToken) === Number(current.fenceToken);
                    }
                    return digest;
                }
            });
            try {
                await save(Uint8Array.from([51,52,53,54,55]));
            } catch (error) {
                migrationError = String(error?.message || error);
            } finally {
                if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                else delete crypto.subtle.digest;
            }

            const after = await readRecord();
            const oldChunkAfter = await readChunk(seeded.chunkPrefix);
            return {
                digestCalls, ownerChanged, migrationError,
                oldRecordUnchanged: JSON.stringify(after) === JSON.stringify(legacyBefore),
                oldPrefixBefore: seeded.chunkPrefix,
                oldPrefixAfter: after?.chunkPrefix || null,
                oldChunkCountBefore,
                oldChunkCountAfter: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(oldChunkAfter) === JSON.stringify(oldChunkBefore),
                hashStillMissing: !Array.isArray(after?.chunkSha256),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(after || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };
        }""")
        self.assertTrue(result["ownerChanged"], result)
        self.assertGreaterEqual(result["digestCalls"], 2, result)
        self.assertEqual(result["digestCalls"], 2, result)
        self.assertTrue(result["migrationError"], result)
        self.assertTrue(result["oldRecordUnchanged"], result)
        self.assertEqual(result["oldPrefixAfter"], result["oldPrefixBefore"], result)
        self.assertGreater(result["oldChunkCountBefore"], 0, result)
        self.assertEqual(result["oldChunkCountAfter"], result["oldChunkCountBefore"], result)
        self.assertTrue(result["oldChunkBytesUnchanged"], result)
        self.assertTrue(result["hashStillMissing"], result)
        self.assertTrue(result["hashPropertyAbsent"], result)
        self.assertTrue(result["safeMode"], result)


    def test_stage57_legacy_chunk_hash_migration_stops_on_fence_only_change(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-fence-only-migration';
            const oldBytes = Uint8Array.from([41,42,43,44,45,46]);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readLock = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreLocks', 'readonly');
                    const req = tx.objectStore('restoreLocks').get('global-mutation');
                    req.onsuccess = () => { tx.__row = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__row);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + '00000000');
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy fence fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await new Promise((resolve, reject) => {
                    const txdb = openVideoDB();
                    txdb.then(database => {
                        const tx = database.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacyRecord, key);
                        tx.oncomplete = () => { database.close(); resolve(); };
                        tx.onerror = () => { database.close(); reject(tx.error); };
                        tx.onabort = () => { database.close(); reject(tx.error); };
                    }, reject);
                }); } finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBefore = await readChunk(seeded.chunkPrefix);
            const oldChunkCountBefore = await countChunks(seeded.chunkPrefix);
            if (Array.isArray(legacyBefore?.chunkSha256)) {
                throw new Error('fixture did not create a legacy record without chunkSha256');
            }

            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
            let digestCalls = 0, fenceChanged = false, changedLock = null, migrationError = null;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    const digest = await originalDigest(...args);
                    digestCalls++;
                    // #1 hashes the replacement input; #2 hashes the legacy video chunk.
                    if (digestCalls === 2 && !fenceChanged) {
                        const current = await readLock();
                        if (!current) throw new Error('global mutation lock row disappeared during fixture');
                        const db = await openVideoDB();
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreLocks', 'readwrite');
                            const store = tx.objectStore('restoreLocks');
                            const req = store.get('global-mutation');
                            req.onsuccess = () => {
                                const row = req.result;
                                store.put({
                                    ...row,
                                    fenceToken: Number(row.fenceToken) + 1
                                });
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                        changedLock = await readLock();
                        fenceChanged = !!changedLock &&
                            changedLock.ownerId === current.ownerId &&
                            Number(changedLock.fenceToken) === Number(current.fenceToken) + 1;
                    }
                    return digest;
                }
            });
            try {
                await save(Uint8Array.from([51,52,53,54,55]));
            } catch (error) {
                migrationError = String(error?.message || error);
            } finally {
                if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                else delete crypto.subtle.digest;
            }

            const after = await readRecord();
            const oldChunkAfter = await readChunk(seeded.chunkPrefix);
            return {
                digestCalls, fenceChanged, migrationError,
                oldRecordUnchanged: JSON.stringify(after) === JSON.stringify(legacyBefore),
                oldPrefixBefore: seeded.chunkPrefix,
                oldPrefixAfter: after?.chunkPrefix || null,
                oldChunkCountBefore,
                oldChunkCountAfter: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(oldChunkAfter) === JSON.stringify(oldChunkBefore),
                hashStillMissing: !Array.isArray(after?.chunkSha256),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(after || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };
        }""")
        self.assertTrue(result["fenceChanged"], result)
        self.assertGreaterEqual(result["digestCalls"], 2, result)
        self.assertEqual(result["digestCalls"], 2, result)
        self.assertTrue(result["migrationError"], result)
        self.assertTrue(result["oldRecordUnchanged"], result)
        self.assertEqual(result["oldPrefixAfter"], result["oldPrefixBefore"], result)
        self.assertGreater(result["oldChunkCountBefore"], 0, result)
        self.assertEqual(result["oldChunkCountAfter"], result["oldChunkCountBefore"], result)
        self.assertTrue(result["oldChunkBytesUnchanged"], result)
        self.assertTrue(result["hashStillMissing"], result)
        self.assertTrue(result["hashPropertyAbsent"], result)
        self.assertTrue(result["safeMode"], result)


    def test_stage57_legacy_multichunk_migration_stops_after_second_chunk_on_owner_change(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-multi-owner-migration';
            const oldBytes = new Uint8Array(1024 * 1024 + 17).fill(41);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readLock = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreLocks', 'readonly');
                    const req = tx.objectStore('restoreLocks').get('global-mutation');
                    req.onsuccess = () => { tx.__row = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__row);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async (prefix, index) => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + String(index).padStart(8, '0'));
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy fence fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await new Promise((resolve, reject) => {
                    const txdb = openVideoDB();
                    txdb.then(database => {
                        const tx = database.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacyRecord, key);
                        tx.oncomplete = () => { database.close(); resolve(); };
                        tx.onerror = () => { database.close(); reject(tx.error); };
                        tx.onabort = () => { database.close(); reject(tx.error); };
                    }, reject);
                }); } finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBytesBefore = await Promise.all(Array.from({length: seeded.chunkCount}, (_, index) => readChunk(seeded.chunkPrefix, index)));
            const oldChunkCountBefore = await countChunks(seeded.chunkPrefix);
            if (Array.isArray(legacyBefore?.chunkSha256)) {
                throw new Error('fixture did not create a legacy record without chunkSha256');
            }

            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
            let digestCalls = 0, ownerChanged = false, changedLock = null, migrationError = null;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    const digest = await originalDigest(...args);
                    digestCalls++;
                    // #1 hashes replacement input; #2/#3 hash legacy chunks 0/1.
                    if (digestCalls === 3 && !ownerChanged) {
                        const current = await readLock();
                        if (!current) throw new Error('global mutation lock row disappeared during fixture');
                        const db = await openVideoDB();
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreLocks', 'readwrite');
                            const store = tx.objectStore('restoreLocks');
                            const req = store.get('global-mutation');
                            req.onsuccess = () => {
                                const row = req.result;
                                store.put({
                                    ...row,
                                    ownerId: 'stage57-stale-legacy-owner'
                                });
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                        changedLock = await readLock();
                        ownerChanged = !!changedLock &&
                            changedLock.ownerId === 'stage57-stale-legacy-owner' &&
                            Number(changedLock.fenceToken) === Number(current.fenceToken);
                    }
                    return digest;
                }
            });
            try {
                await save(Uint8Array.from([51,52,53,54,55]));
            } catch (error) {
                migrationError = String(error?.message || error);
            } finally {
                if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                else delete crypto.subtle.digest;
            }

            const after = await readRecord();
            const oldChunkBytesAfter = await Promise.all(Array.from({length: seeded.chunkCount}, (_, index) => readChunk(seeded.chunkPrefix, index)));
            return {
                digestCalls, ownerChanged, migrationError,
                oldRecordUnchanged: JSON.stringify(after) === JSON.stringify(legacyBefore),
                oldPrefixBefore: seeded.chunkPrefix,
                oldPrefixAfter: after?.chunkPrefix || null,
                oldChunkCountBefore,
                oldChunkCountAfter: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(oldChunkBytesAfter) === JSON.stringify(oldChunkBytesBefore),
                hashStillMissing: !Array.isArray(after?.chunkSha256),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(after || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };
        }""")
        self.assertTrue(result["ownerChanged"], result)
        self.assertEqual(result["digestCalls"], 3, result)
        self.assertTrue(result["migrationError"], result)
        self.assertTrue(result["oldRecordUnchanged"], result)
        self.assertEqual(result["oldPrefixAfter"], result["oldPrefixBefore"], result)
        self.assertEqual(result["oldChunkCountBefore"], 2, result)
        self.assertEqual(result["oldChunkCountAfter"], result["oldChunkCountBefore"], result)
        self.assertTrue(result["oldChunkBytesUnchanged"], result)
        self.assertTrue(result["hashStillMissing"], result)
        self.assertTrue(result["hashPropertyAbsent"], result)
        self.assertTrue(result["safeMode"], result)



    def test_stage57_legacy_multichunk_migration_stops_after_second_chunk_on_fence_change(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-multi-fence-migration';
            const oldBytes = new Uint8Array(1024 * 1024 + 17).fill(41);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readLock = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('restoreLocks', 'readonly');
                    const req = tx.objectStore('restoreLocks').get('global-mutation');
                    req.onsuccess = () => { tx.__row = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__row);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async (prefix, index) => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + String(index).padStart(8, '0'));
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );

            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy fence fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await new Promise((resolve, reject) => {
                    const txdb = openVideoDB();
                    txdb.then(database => {
                        const tx = database.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacyRecord, key);
                        tx.oncomplete = () => { database.close(); resolve(); };
                        tx.onerror = () => { database.close(); reject(tx.error); };
                        tx.onabort = () => { database.close(); reject(tx.error); };
                    }, reject);
                }); } finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBytesBefore = await Promise.all(Array.from({length: seeded.chunkCount}, (_, index) => readChunk(seeded.chunkPrefix, index)));
            const oldChunkCountBefore = await countChunks(seeded.chunkPrefix);
            if (Array.isArray(legacyBefore?.chunkSha256)) {
                throw new Error('fixture did not create a legacy record without chunkSha256');
            }

            const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
            const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
            let digestCalls = 0, fenceChanged = false, changedLock = null, migrationError = null;
            Object.defineProperty(crypto.subtle, 'digest', {
                configurable: true,
                value: async (...args) => {
                    const digest = await originalDigest(...args);
                    digestCalls++;
                    // #1 hashes replacement input; #2/#3 hash legacy chunks 0/1.
                    if (digestCalls === 3 && !fenceChanged) {
                        const current = await readLock();
                        if (!current) throw new Error('global mutation lock row disappeared during fixture');
                        const db = await openVideoDB();
                        try { await new Promise((resolve, reject) => {
                            const tx = db.transaction('restoreLocks', 'readwrite');
                            const store = tx.objectStore('restoreLocks');
                            const req = store.get('global-mutation');
                            req.onsuccess = () => {
                                const row = req.result;
                                store.put({
                                    ...row,
                                    fenceToken: Number(row.fenceToken) + 1
                                });
                            };
                            req.onerror = () => reject(req.error);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        }); } finally { db.close(); }
                        changedLock = await readLock();
                        fenceChanged = !!changedLock &&
                            changedLock.ownerId === current.ownerId &&
                            Number(changedLock.fenceToken) === Number(current.fenceToken) + 1;
                    }
                    return digest;
                }
            });
            try {
                await save(Uint8Array.from([51,52,53,54,55]));
            } catch (error) {
                migrationError = String(error?.message || error);
            } finally {
                if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                else delete crypto.subtle.digest;
            }

            const after = await readRecord();
            const oldChunkBytesAfter = await Promise.all(Array.from({length: seeded.chunkCount}, (_, index) => readChunk(seeded.chunkPrefix, index)));
            return {
                digestCalls, fenceChanged, migrationError,
                oldRecordUnchanged: JSON.stringify(after) === JSON.stringify(legacyBefore),
                oldPrefixBefore: seeded.chunkPrefix,
                oldPrefixAfter: after?.chunkPrefix || null,
                oldChunkCountBefore,
                oldChunkCountAfter: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(oldChunkBytesAfter) === JSON.stringify(oldChunkBytesBefore),
                hashStillMissing: !Array.isArray(after?.chunkSha256),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(after || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };
        }""")
        self.assertTrue(result["fenceChanged"], result)
        self.assertEqual(result["digestCalls"], 3, result)
        self.assertTrue(result["migrationError"], result)
        self.assertTrue(result["oldRecordUnchanged"], result)
        self.assertEqual(result["oldPrefixAfter"], result["oldPrefixBefore"], result)
        self.assertEqual(result["oldChunkCountBefore"], 2, result)
        self.assertEqual(result["oldChunkCountAfter"], result["oldChunkCountBefore"], result)
        self.assertTrue(result["oldChunkBytesUnchanged"], result)
        self.assertTrue(result["hashStillMissing"], result)
        self.assertTrue(result["hashPropertyAbsent"], result)
        self.assertTrue(result["safeMode"], result)


    def test_stage57_legacy_chunk_hash_migration_retries_after_transient_chunk_read_failure(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const key = 'stage57-legacy-read-retry';
            const oldBytes = Uint8Array.from([61,62,63,64,65,66,67]);
            const replacementBytes = Uint8Array.from([71,72,73,74,75]);
            const readRecord = async () => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunk = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').get(prefix + '00000000');
                    req.onsuccess = () => { tx.__bytes = req.result ? Array.from(req.result) : null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__bytes);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const writeRecord = async record => {
                const ctx = window.__rikuMutationContext;
                if (ctx) ctx.videoMetadataWriteAuthorized = true;
                const db = await openVideoDB();
                try { await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readwrite');
                    tx.objectStore('videos').put(record, key);
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally {
                    db.close();
                    if (ctx) ctx.videoMetadataWriteAuthorized = false;
                }
            };
            const save = bytes => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );
            await save(oldBytes);
            const seeded = await readRecord();
            if (!seeded) throw new Error('legacy retry fixture did not persist its initial video');
            const {chunkSha256, ...legacyRecord} = seeded;
            await withGlobalMutationLock('storeClipVideo', async ctx => {
                ctx.videoMetadataWriteAuthorized = true;
                try { await writeRecord(legacyRecord); }
                finally { ctx.videoMetadataWriteAuthorized = false; }
            });
            const legacyBefore = await readRecord();
            const oldChunkBefore = await readChunk(seeded.chunkPrefix);
            const oldCountBefore = await countChunks(seeded.chunkPrefix);

            const originalGet = IDBObjectStore.prototype.get;
            let readAbortInjected = false, firstError = null;
            IDBObjectStore.prototype.get = function(primaryKey) {
                const request = originalGet.call(this, primaryKey);
                if (!readAbortInjected && this.name === 'videoChunks') {
                    readAbortInjected = true;
                    queueMicrotask(() => { try { request.transaction.abort(); } catch (_) {} });
                }
                return request;
            };
            try { await save(replacementBytes); }
            catch (error) { firstError = String(error?.message || error); }
            finally { IDBObjectStore.prototype.get = originalGet; }

            const afterFailure = await readRecord();
            const failureChunk = await readChunk(seeded.chunkPrefix);
            const failure = {
                readAbortInjected, firstError,
                recordUnchanged: JSON.stringify(afterFailure) === JSON.stringify(legacyBefore),
                oldChunkCount: await countChunks(seeded.chunkPrefix),
                oldChunkBytesUnchanged: JSON.stringify(failureChunk) === JSON.stringify(oldChunkBefore),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(afterFailure || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };

            const originalRecordChange = window.__rikuRecordVideoChange;
            let migratedOldHashes = null;
            window.__rikuRecordVideoChange = async change => {
                if (change.key === key) migratedOldHashes = change.oldRecord?.chunkSha256 || null;
                return originalRecordChange(change);
            };
            let retryError = null;
            try { await save(replacementBytes); }
            catch (error) { retryError = String(error?.message || error); }
            finally { window.__rikuRecordVideoChange = originalRecordChange; }
            const afterRetry = await readRecord();
            const expectedDigest = await crypto.subtle.digest('SHA-256', oldBytes);
            const expectedOldHash = [...new Uint8Array(expectedDigest)]
                .map(value => value.toString(16).padStart(2, '0')).join('');
            return {
                failure, retryError, migratedOldHashes, expectedOldHash,
                oldCountBefore,
                oldCountAfter: await countChunks(seeded.chunkPrefix),
                oldPrefixBefore: seeded.chunkPrefix,
                activePrefixAfter: afterRetry?.chunkPrefix || null,
                activeHashCount: afterRetry?.chunkSha256?.length || 0,
                activeSize: afterRetry?.size || 0
            };
        }""")
        failure = result["failure"]
        self.assertTrue(failure["readAbortInjected"], result)
        self.assertTrue(failure["firstError"], result)
        self.assertTrue(failure["recordUnchanged"], result)
        self.assertGreater(failure["oldChunkCount"], 0, result)
        self.assertTrue(failure["oldChunkBytesUnchanged"], result)
        self.assertTrue(failure["hashPropertyAbsent"], result)
        self.assertFalse(failure["safeMode"], result)
        self.assertIsNone(result["retryError"], result)
        self.assertEqual(result["migratedOldHashes"], [result["expectedOldHash"]], result)
        self.assertEqual(result["oldCountBefore"], 1, result)
        self.assertEqual(result["oldCountAfter"], 0, result)
        self.assertNotEqual(result["activePrefixAfter"], result["oldPrefixBefore"], result)
        self.assertEqual(result["activeHashCount"], 1, result)
        self.assertEqual(result["activeSize"], 5, result)


    def test_stage57_legacy_chunk_hash_migration_two_tab_conflict_preserves_then_retries(self):
        page = self.page
        page.set_default_timeout(120000)
        second = page.context.new_page()
        try:
            second.goto(self.base_url, wait_until="load")
            page.wait_for_function("typeof storeClipVideo === 'function'")
            page.wait_for_function(
                "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
                timeout=15000,
            )
            second.wait_for_function(
                "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
                timeout=15000,
            )
            seeded = page.evaluate("""async () => {
                const key = 'stage57-legacy-two-tab-migration';
                const oldBytes = Uint8Array.from([81,82,83,84,85]);
                const readRecord = async () => {
                    const db = await openVideoDB();
                    try { return await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally { db.close(); }
                };
                const writeRecord = async record => {
                    const ctx = window.__rikuMutationContext;
                    if (ctx) ctx.videoMetadataWriteAuthorized = true;
                    const db = await openVideoDB();
                    try { await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(record, key);
                        tx.oncomplete = resolve;
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally {
                        db.close();
                        if (ctx) ctx.videoMetadataWriteAuthorized = false;
                    }
                };
                await withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([oldBytes], {type:'video/mp4'}))
                );
                const record = await readRecord();
                if (!record) throw new Error('two-tab legacy fixture did not persist its video');
                const {chunkSha256, ...legacy} = record;
                await withGlobalMutationLock('storeClipVideo', async ctx => {
                    ctx.videoMetadataWriteAuthorized = true;
                    try { await writeRecord(legacy); }
                    finally { ctx.videoMetadataWriteAuthorized = false; }
                });
                return {key, prefix:record.chunkPrefix, count:record.chunkCount};
            }""")
            page.evaluate("""() => {
                window.__stage57MigrationLockEntered = false;
                window.__stage57MigrationLockPromise = withGlobalMutationLock(
                    'stage57-migration-hold',
                    async () => {
                        window.__stage57MigrationLockEntered = true;
                        await new Promise(resolve => { window.__releaseStage57MigrationLock = resolve; });
                    }
                );
            }""")
            page.wait_for_function("window.__stage57MigrationLockEntered === true")
            second.evaluate("""key => {
                window.__stage57ConflictFinished = false;
                window.__stage57ConflictError = null;
                window.__stage57ConflictPromise = withGlobalMutationLock(
                    'storeClipVideo',
                    () => storeClipVideo(key, new Blob([Uint8Array.from([91,92,93,94])], {type:'video/mp4'}))
                ).then(() => { window.__stage57ConflictFinished = true; })
                 .catch(error => { window.__stage57ConflictError = String(error?.message || error); });
            }""", seeded["key"])
            second.wait_for_function("!!window.__stage57ConflictError || window.__stage57ConflictFinished")
            self.assertFalse(second.evaluate("window.__stage57ConflictFinished"))
            self.assertIn("別のタブで保存処理中", second.evaluate("window.__stage57ConflictError"))

            unchanged = page.evaluate("""async ({key, prefix}) => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction(['videos','videoChunks'], 'readonly');
                    const recordReq = tx.objectStore('videos').get(key);
                    const chunkReq = tx.objectStore('videoChunks').get(prefix + '00000000');
                    const result = {};
                    recordReq.onsuccess = () => { result.record = recordReq.result || null; };
                    chunkReq.onsuccess = () => { result.chunk = chunkReq.result ? Array.from(chunkReq.result) : null; };
                    tx.oncomplete = () => resolve(result);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            }""", seeded)
            self.assertEqual(unchanged["record"]["chunkPrefix"], seeded["prefix"])
            self.assertNotIn("chunkSha256", unchanged["record"])
            self.assertEqual(len(unchanged["chunk"]), 5)
            self.assertEqual(unchanged["chunk"][0], 81)
            self.assertEqual(unchanged["chunk"][-1], 85)

            page.evaluate("window.__releaseStage57MigrationLock()")
            page.evaluate("window.__stage57MigrationLockPromise")
            second.evaluate("""key => {
                window.__stage57ConflictError = null;
                window.__stage57ConflictFinished = false;
                window.__stage57RetryHashes = null;
                const original = window.__rikuRecordVideoChange;
                window.__rikuRecordVideoChange = async change => {
                    if (change.key === key) window.__stage57RetryHashes = change.oldRecord?.chunkSha256 || null;
                    return original(change);
                };
                window.__stage57RetryPromise = withGlobalMutationLock(
                    'storeClipVideo',
                    () => storeClipVideo(key, new Blob([Uint8Array.from([91,92,93,94])], {type:'video/mp4'}))
                ).then(() => { window.__stage57ConflictFinished = true; })
                 .catch(error => { window.__stage57ConflictError = String(error?.message || error); });
            }""", seeded["key"])
            second.wait_for_function(
                "window.__stage57ConflictFinished || !!window.__stage57ConflictError",
                timeout=30000,
            )
            self.assertTrue(
                second.evaluate("window.__stage57ConflictFinished"),
                second.evaluate("window.__stage57ConflictError || null") or "two-tab migration retry timed out",
            )
            after = second.evaluate("""async key => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction(['videos','videoChunks'], 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            }""", seeded["key"])
            expected = page.evaluate("""async () => {
                const bytes = Uint8Array.from([81,82,83,84,85]);
                const digest = await crypto.subtle.digest('SHA-256', bytes);
                return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2,'0')).join('');
            }""")
            retry_hashes = second.evaluate("window.__stage57RetryHashes")
            self.assertEqual(retry_hashes, [expected], retry_hashes)
            self.assertNotEqual(after["chunkPrefix"], seeded["prefix"])
            self.assertEqual(after["size"], 4)
            self.assertEqual(len(after["chunkSha256"]), 1)
        finally:
            try:
                page.evaluate("window.__releaseStage57MigrationLock && window.__releaseStage57MigrationLock()")
                page.evaluate("window.__stage57MigrationLockPromise")
            except Exception:
                pass
            second.close()


    def test_stage57_legacy_multichunk_migration_success_and_second_chunk_retry(self):
        page = self.page
        page.set_default_timeout(120000)
        page.wait_for_function("typeof storeClipVideo === 'function'")
        page.wait_for_function(
            "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
            timeout=15000,
        )
        result = page.evaluate("""async () => {
            const chunkSize = 1024 * 1024;
            const makeLegacy = async (key, bytes) => {
                const save = data => withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([data], {type:'video/mp4'}))
                );
                await save(bytes);
                const db = await openVideoDB();
                let record;
                try { record = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
                if (!record) throw new Error('multichunk legacy fixture did not persist');
                const {chunkSha256, ...legacy} = record;
                await withGlobalMutationLock('storeClipVideo', async ctx => {
                    ctx.videoMetadataWriteAuthorized = true;
                    const legacyDb = await openVideoDB();
                    try { await new Promise((resolve, reject) => {
                        const tx = legacyDb.transaction('videos', 'readwrite');
                        tx.objectStore('videos').put(legacy, key);
                        tx.oncomplete = resolve;
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    }); } finally {
                        legacyDb.close();
                        ctx.videoMetadataWriteAuthorized = false;
                    }
                });
                return record;
            };
            const readRecord = async key => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const req = tx.objectStore('videos').get(key);
                    req.onsuccess = () => { tx.__record = req.result || null; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__record);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const readChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').getAll(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => {
                        tx.__chunks = req.result.map(value => Array.from(value));
                    };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__chunks);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const countChunks = async prefix => {
                const db = await openVideoDB();
                try { return await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const req = tx.objectStore('videoChunks').count(
                        IDBKeyRange.bound(prefix, prefix + '\\uffff')
                    );
                    req.onsuccess = () => { tx.__count = req.result; };
                    req.onerror = () => reject(req.error);
                    tx.oncomplete = () => resolve(tx.__count);
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                }); } finally { db.close(); }
            };
            const expectedHashes = async bytes => {
                const hashes = [];
                for (let offset = 0; offset < bytes.length; offset += chunkSize) {
                    const digest = await crypto.subtle.digest(
                        'SHA-256', bytes.slice(offset, Math.min(bytes.length, offset + chunkSize))
                    );
                    hashes.push([...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join(''));
                }
                return hashes;
            };
            const save = (key, bytes) => withGlobalMutationLock('storeClipVideo', () =>
                storeClipVideo(key, new Blob([bytes], {type:'video/mp4'}))
            );
            const oldBytes = new Uint8Array(chunkSize + 17).fill(57);
            const replacement = Uint8Array.from([91,92,93,94,95]);

            const successKey = 'stage57-legacy-multichunk-success';
            const oldSuccess = await makeLegacy(successKey, oldBytes);
            const successChunksBefore = await readChunks(oldSuccess.chunkPrefix);
            let successMigratedHashes = null;
            const originalRecordChange = window.__rikuRecordVideoChange;
            window.__rikuRecordVideoChange = async change => {
                if (change.key === successKey) successMigratedHashes = change.oldRecord?.chunkSha256 || null;
                return originalRecordChange(change);
            };
            await save(successKey, replacement);
            window.__rikuRecordVideoChange = originalRecordChange;
            const successCurrent = await readRecord(successKey);
            const success = {
                expectedHashes: await expectedHashes(oldBytes),
                migratedHashes: successMigratedHashes,
                oldChunkCountBefore: successChunksBefore.length,
                oldChunkCountAfter: await countChunks(oldSuccess.chunkPrefix),
                activePrefixChanged: successCurrent?.chunkPrefix !== oldSuccess.chunkPrefix,
                activeHashCount: successCurrent?.chunkSha256?.length || 0
            };

            const retryKey = 'stage57-legacy-multichunk-second-read-retry';
            const oldRetry = await makeLegacy(retryKey, oldBytes);
            const retryRecordBefore = await readRecord(retryKey);
            const retryChunksBefore = await readChunks(oldRetry.chunkPrefix);
            const originalGet = IDBObjectStore.prototype.get;
            let secondChunkAbortInjected = false, firstError = null;
            IDBObjectStore.prototype.get = function(primaryKey) {
                const request = originalGet.call(this, primaryKey);
                if (!secondChunkAbortInjected &&
                    this.name === 'videoChunks' &&
                    primaryKey === oldRetry.chunkPrefix + '00000001') {
                    secondChunkAbortInjected = true;
                    queueMicrotask(() => { try { request.transaction.abort(); } catch (_) {} });
                }
                return request;
            };
            try { await save(retryKey, replacement); }
            catch (error) { firstError = String(error?.message || error); }
            finally { IDBObjectStore.prototype.get = originalGet; }
            const retryAfterFailure = await readRecord(retryKey);
            const retryChunksAfterFailure = await readChunks(oldRetry.chunkPrefix);
            const failure = {
                secondChunkAbortInjected,
                firstError,
                recordUnchanged: JSON.stringify(retryAfterFailure) === JSON.stringify(retryRecordBefore),
                chunkCountBefore: retryChunksBefore.length,
                chunkCountAfter: retryChunksAfterFailure.length,
                allChunkBytesUnchanged: JSON.stringify(retryChunksAfterFailure) === JSON.stringify(retryChunksBefore),
                hashPropertyAbsent: !Object.prototype.hasOwnProperty.call(retryAfterFailure || {}, 'chunkSha256'),
                safeMode: !!window.__rikuMutationSafeMode
            };

            let retryMigratedHashes = null, retryError = null;
            window.__rikuRecordVideoChange = async change => {
                if (change.key === retryKey) retryMigratedHashes = change.oldRecord?.chunkSha256 || null;
                return originalRecordChange(change);
            };
            try { await save(retryKey, replacement); }
            catch (error) { retryError = String(error?.message || error); }
            finally { window.__rikuRecordVideoChange = originalRecordChange; }
            const retryCurrent = await readRecord(retryKey);
            const retry = {
                expectedHashes: await expectedHashes(oldBytes),
                migratedHashes: retryMigratedHashes,
                oldChunkCountAfter: await countChunks(oldRetry.chunkPrefix),
                activePrefixChanged: retryCurrent?.chunkPrefix !== oldRetry.chunkPrefix,
                activeHashCount: retryCurrent?.chunkSha256?.length || 0,
                activeSize: retryCurrent?.size || 0
            };
            return {success, failure, retryError, retry};
        }""")
        success = result["success"]
        self.assertEqual(success["oldChunkCountBefore"], 2, result)
        self.assertEqual(success["migratedHashes"], success["expectedHashes"], result)
        self.assertEqual(success["oldChunkCountAfter"], 0, result)
        self.assertTrue(success["activePrefixChanged"], result)
        self.assertEqual(success["activeHashCount"], 1, result)

        failure = result["failure"]
        self.assertTrue(failure["secondChunkAbortInjected"], result)
        self.assertTrue(failure["firstError"], result)
        self.assertTrue(failure["recordUnchanged"], result)
        self.assertEqual(failure["chunkCountBefore"], 2, result)
        self.assertEqual(failure["chunkCountAfter"], 2, result)
        self.assertTrue(failure["allChunkBytesUnchanged"], result)
        self.assertTrue(failure["hashPropertyAbsent"], result)
        self.assertFalse(failure["safeMode"], result)

        retry = result["retry"]
        self.assertIsNone(result["retryError"], result)
        self.assertEqual(retry["migratedHashes"], retry["expectedHashes"], result)
        self.assertEqual(retry["oldChunkCountAfter"], 0, result)
        self.assertTrue(retry["activePrefixChanged"], result)
        self.assertEqual(retry["activeHashCount"], 1, result)
        self.assertEqual(retry["activeSize"], 5, result)


    def test_stage57_legacy_multichunk_simultaneous_two_tab_migration_serializes_and_preserves_old_chunks(self):
        page = self.page
        page.set_default_timeout(120000)
        second = page.context.new_page()
        try:
            second.goto(self.base_url, wait_until="load")
            for tab in (page, second):
                tab.wait_for_function("typeof storeClipVideo === 'function'")
                tab.wait_for_function(
                    "window.__rikuMutationRecoveryReady && window.__rikuMutationRecoveryReady()",
                    timeout=15000,
                )

            seeded = page.evaluate("""async () => {
                const key = 'stage57-legacy-simultaneous-two-tab';
                const oldBytes = new Uint8Array(1024 * 1024 + 23).fill(63);
                await withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([oldBytes], {type:'video/mp4'}))
                );
                const db = await openVideoDB();
                let record;
                try {
                    record = await new Promise((resolve, reject) => {
                        const tx = db.transaction('videos', 'readonly');
                        const req = tx.objectStore('videos').get(key);
                        req.onsuccess = () => { tx.__record = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__record);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    });
                } finally { db.close(); }
                if (!record || record.chunkCount !== 2) {
                    throw new Error('simultaneous migration fixture did not create two chunks');
                }
                const {chunkSha256, ...legacy} = record;
                await withGlobalMutationLock('storeClipVideo', async ctx => {
                    ctx.videoMetadataWriteAuthorized = true;
                    const legacyDb = await openVideoDB();
                    try {
                        await new Promise((resolve, reject) => {
                            const tx = legacyDb.transaction('videos', 'readwrite');
                            tx.objectStore('videos').put(legacy, key);
                            tx.oncomplete = resolve;
                            tx.onerror = () => reject(tx.error);
                            tx.onabort = () => reject(tx.error);
                        });
                    } finally {
                        legacyDb.close();
                        ctx.videoMetadataWriteAuthorized = false;
                    }
                });
                return {key, prefix:record.chunkPrefix, count:record.chunkCount, oldBytes:Array.from(oldBytes)};
            }""")

            page.evaluate("""({key}) => {
                window.__stage57WinnerPaused = false;
                window.__stage57WinnerFinished = false;
                window.__stage57WinnerError = null;
                window.__stage57WinnerDigestCalls = 0;
                window.__stage57WinnerPausedDigestCalls = 0;
                window.__stage57WinnerHashes = null;
                window.__stage57WinnerLock = null;
                window.__stage57ReleaseWinner = null;
                const originalDigest = crypto.subtle.digest.bind(crypto.subtle);
                const digestDescriptor = Object.getOwnPropertyDescriptor(crypto.subtle, 'digest');
                window.__stage57DigestRestore = () => {
                    if (digestDescriptor) Object.defineProperty(crypto.subtle, 'digest', digestDescriptor);
                    else delete crypto.subtle.digest;
                };
                Object.defineProperty(crypto.subtle, 'digest', {
                    configurable: true,
                    value: async (...args) => {
                        const result = await originalDigest(...args);
                        window.__stage57WinnerDigestCalls++;
                        // #1 hashes replacement input; #2/#3 hash the two legacy chunks.
                        if (window.__stage57WinnerDigestCalls === 3) {
                            const ctx = window.__rikuMutationContext;
                            window.__stage57WinnerLock = ctx ? {
                                ownerId:ctx.ownerId, fenceToken:Number(ctx.fenceToken)
                            } : null;
                            window.__stage57WinnerPausedDigestCalls = window.__stage57WinnerDigestCalls;
                            window.__stage57WinnerPaused = true;
                            await new Promise(resolve => { window.__stage57ReleaseWinner = resolve; });
                        }
                        return result;
                    }
                });
                const originalRecordChange = window.__rikuRecordVideoChange;
                window.__rikuRecordVideoChange = async change => {
                    if (change.key === key) {
                        window.__stage57WinnerHashes = change.oldRecord?.chunkSha256 || null;
                    }
                    return originalRecordChange(change);
                };
                window.__stage57WinnerPromise = withGlobalMutationLock('storeClipVideo', () =>
                    storeClipVideo(key, new Blob([Uint8Array.from([101,102,103,104,105])], {type:'video/mp4'}))
                ).then(() => { window.__stage57WinnerFinished = true; })
                 .catch(error => { window.__stage57WinnerError = String(error?.message || error); })
                 .finally(() => {
                    window.__stage57DigestRestore();
                    window.__rikuRecordVideoChange = originalRecordChange;
                 });
            }""", seeded)
            page.wait_for_function("window.__stage57WinnerPaused === true")

            lockDuringMigration = second.evaluate("""async () => {
                const db = await openVideoDB();
                try {
                    return await new Promise((resolve, reject) => {
                        const tx = db.transaction('restoreLocks', 'readonly');
                        const req = tx.objectStore('restoreLocks').get('global-mutation');
                        req.onsuccess = () => { tx.__row = req.result || null; };
                        req.onerror = () => reject(req.error);
                        tx.oncomplete = () => resolve(tx.__row);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    });
                } finally { db.close(); }
            }""")
            winnerLock = page.evaluate("window.__stage57WinnerLock")
            self.assertIsNotNone(winnerLock, winnerLock)
            self.assertEqual(lockDuringMigration["ownerId"], winnerLock["ownerId"], lockDuringMigration)
            self.assertEqual(
                int(lockDuringMigration["fenceToken"]), winnerLock["fenceToken"], lockDuringMigration
            )

            second.evaluate("""key => {
                window.__stage57LoserFinished = false;
                window.__stage57LoserError = null;
                window.__stage57LoserPromise = storeClipVideo(
                    key, new Blob([Uint8Array.from([111,112,113,114])], {type:'video/mp4'})
                ).then(() => { window.__stage57LoserFinished = true; })
                 .catch(error => {
                    window.__stage57LoserError = String(error?.message || error);
                 });
            }""", seeded["key"])
            second.wait_for_function(
                "window.__stage57LoserFinished === true || !!window.__stage57LoserError"
            )
            self.assertFalse(second.evaluate("window.__stage57LoserFinished"))
            self.assertIn(
                "別のタブで保存処理中",
                second.evaluate("window.__stage57LoserError"),
            )

            pausedSnapshot = second.evaluate("""async ({key, prefix}) => {
                const db = await openVideoDB();
                try {
                    return await new Promise((resolve, reject) => {
                        const tx = db.transaction(['videos','videoChunks'], 'readonly');
                        const recordReq = tx.objectStore('videos').get(key);
                        const chunksReq = tx.objectStore('videoChunks').getAll(
                            IDBKeyRange.bound(prefix, prefix + '\\\\uffff')
                        );
                        const result = {};
                        recordReq.onsuccess = () => { result.record = recordReq.result || null; };
                        chunksReq.onsuccess = () => {
                            result.chunks = chunksReq.result.map(value => Array.from(value));
                        };
                        tx.oncomplete = () => resolve(result);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    });
                } finally { db.close(); }
            }""", seeded)
            self.assertEqual(pausedSnapshot["record"]["chunkPrefix"], seeded["prefix"])
            self.assertNotIn("chunkSha256", pausedSnapshot["record"])
            self.assertEqual(len(pausedSnapshot["chunks"]), 2)
            self.assertEqual(
                pausedSnapshot["chunks"],
                [seeded["oldBytes"][:1024 * 1024], seeded["oldBytes"][1024 * 1024:]],
            )

            page.evaluate("window.__stage57ReleaseWinner()")
            page.wait_for_function(
                "window.__stage57WinnerFinished === true || !!window.__stage57WinnerError",
                timeout=60000,
            )
            self.assertTrue(
                page.evaluate("window.__stage57WinnerFinished"),
                page.evaluate("window.__stage57WinnerError"),
            )
            finalState = second.evaluate("""async ({key, prefix}) => {
                const db = await openVideoDB();
                try {
                    return await new Promise((resolve, reject) => {
                        const tx = db.transaction(['videos','videoChunks'], 'readonly');
                        const recordReq = tx.objectStore('videos').get(key);
                        const chunksReq = tx.objectStore('videoChunks').count(
                            IDBKeyRange.bound(prefix, prefix + '\\\\uffff')
                        );
                        const result = {};
                        recordReq.onsuccess = () => { result.record = recordReq.result || null; };
                        chunksReq.onsuccess = () => { result.oldChunkCount = chunksReq.result; };
                        tx.oncomplete = () => resolve(result);
                        tx.onerror = () => reject(tx.error);
                        tx.onabort = () => reject(tx.error);
                    });
                } finally { db.close(); }
            }""", seeded)
            expectedHashes = second.evaluate("""async oldBytes => {
                const hashes = [];
                for (let offset = 0; offset < oldBytes.length; offset += 1024 * 1024) {
                    const digest = await crypto.subtle.digest(
                        'SHA-256', Uint8Array.from(oldBytes.slice(offset, offset + 1024 * 1024))
                    );
                    hashes.push([...new Uint8Array(digest)]
                        .map(value => value.toString(16).padStart(2, '0')).join(''));
                }
                return hashes;
            }""", seeded["oldBytes"])
            self.assertEqual(page.evaluate("window.__stage57WinnerPausedDigestCalls"), 3)
            self.assertGreaterEqual(page.evaluate("window.__stage57WinnerDigestCalls"), 3)
            self.assertEqual(page.evaluate("window.__stage57WinnerHashes"), expectedHashes)
            self.assertNotEqual(finalState["record"]["chunkPrefix"], seeded["prefix"])
            self.assertEqual(finalState["record"]["size"], 5)
            self.assertEqual(len(finalState["record"]["chunkSha256"]), 1)
            self.assertEqual(finalState["oldChunkCount"], 0)
        finally:
            try:
                page.evaluate(
                    "window.__stage57ReleaseWinner && window.__stage57ReleaseWinner(); "
                    "window.__stage57DigestRestore && window.__stage57DigestRestore()"
                )
                page.evaluate("window.__stage57WinnerPromise")
            except Exception:
                pass
            second.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
