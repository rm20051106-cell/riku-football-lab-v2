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


class Stage63BlobStorageMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(QuietHandler, directory=str(ROOT)),
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/index.html" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.playwright = sync_playwright().start()

    def tearDown(self):
        self.playwright.stop()

    def assert_native_blob_storage(self, browser_name):
        browser_type = getattr(self.playwright, browser_name)
        browser = browser_type.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(self.url, wait_until="load")
            page.wait_for_function("typeof window.storeClipVideo === 'function'")
            result = page.evaluate("""async () => {
                const originalArrayBuffer = Blob.prototype.arrayBuffer;
                const largeVideo = new Blob(
                    [new Uint8Array(8 * 1024 * 1024)],
                    {type: 'video/mp4'}
                );
                let arrayBufferCalls = 0, largestArrayBufferSource = 0;
                Blob.prototype.arrayBuffer = function() {
                    arrayBufferCalls++;
                    largestArrayBufferSource = Math.max(largestArrayBufferSource, this.size);
                    if (this.size > 1024 * 1024) throw new Error('full-video ArrayBuffer conversion is forbidden');
                    return originalArrayBuffer.call(this);
                };
                try {
                    await storeClipVideo('stage63-native-blob', largeVideo);
                } finally {
                    Blob.prototype.arrayBuffer = originalArrayBuffer;
                }

                const db = await openVideoDB();
                const raw = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videos', 'readonly');
                    const request = tx.objectStore('videos').get('stage63-native-blob');
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                    tx.onerror = () => reject(tx.error);
                });
                const chunks = await new Promise((resolve, reject) => {
                    const tx = db.transaction('videoChunks', 'readonly');
                    const request = tx.objectStore('videoChunks').getAll();
                    request.onsuccess = () => resolve(request.result.filter((_, i) => i < 8));
                    request.onerror = () => reject(request.error);
                });
                db.close();
                const restored = await getClipVideo('stage63-native-blob');

                // Older records used an ArrayBuffer named blobData. They must remain readable.
                const legacyDb = await openVideoDB();
                await new Promise((resolve, reject) => {
                    const tx = legacyDb.transaction('videos', 'readwrite');
                    tx.objectStore('videos').put({
                        name: 'legacy.webm',
                        type: 'video/webm',
                        blobData: new Uint8Array([1, 2, 3, 4]).buffer,
                        blobType: 'video/webm',
                        size: 4
                    }, 'stage63-legacy');
                    tx.oncomplete = resolve;
                    tx.onerror = () => reject(tx.error);
                    tx.onabort = () => reject(tx.error);
                });
                legacyDb.close();
                const legacy = await getClipVideo('stage63-legacy');

                return {
                    arrayBufferCalls,
                    storageFormat: raw.storageFormat,
                    chunkCount: raw.chunkCount,
                    storedChunkCount: chunks.length,
                    largestStoredChunkBytes: Math.max(...chunks.map(c => c.byteLength)),
                    largestArrayBufferSource,
                    hasLegacyBlobData: Object.prototype.hasOwnProperty.call(raw, 'blobData'),
                    restoredSize: restored?.blob?.size ?? null,
                    restoredType: restored?.blob?.type ?? null,
                    legacySize: legacy?.blob?.size ?? null,
                    legacyType: legacy?.blob?.type ?? null
                };
            }""")
            self.assertEqual(result["arrayBufferCalls"], 8, result)
            self.assertEqual(result["largestArrayBufferSource"], 1024 * 1024, result)
            self.assertEqual(result["storageFormat"], "chunked-v1", result)
            self.assertEqual(result["chunkCount"], 8, result)
            self.assertEqual(result["storedChunkCount"], 8, result)
            self.assertEqual(result["largestStoredChunkBytes"], 1024 * 1024, result)
            self.assertFalse(result["hasLegacyBlobData"], result)
            self.assertEqual(result["restoredSize"], 8 * 1024 * 1024, result)
            self.assertEqual(result["restoredType"], "video/mp4", result)
            self.assertEqual(result["legacySize"], 4, result)
            self.assertEqual(result["legacyType"], "video/webm", result)
        finally:
            context.close()
            browser.close()

    def test_chromium_stores_large_video_blob_without_arraybuffer_copy(self):
        self.assert_native_blob_storage("chromium")

    def test_webkit_stores_large_video_blob_without_arraybuffer_copy(self):
        self.assert_native_blob_storage("webkit")


if __name__ == "__main__":
    unittest.main()
