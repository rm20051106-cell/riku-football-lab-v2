import asyncio
import io
import os
import sys
import unittest
from unittest import mock
from pathlib import Path


class MatchUploadBackendIntegrationTest(unittest.TestCase):
    def test_decode_preflight_accepts_readable_video_and_releases_capture(self):
        if not Path("/app/main.py").exists():
            self.skipTest("Run this integration test inside the backend Docker image")
        sys.path.insert(0, "/app")
        import main

        readable = mock.Mock()
        readable.isOpened.return_value = True
        readable.read.return_value = (True, mock.Mock(shape=(540, 960, 3)))
        with mock.patch.object(main.cv2, "VideoCapture", return_value=readable):
            self.assertTrue(main.can_decode_video_first_frame("readable.mp4"))
        readable.release.assert_called_once()

        high_resolution = mock.Mock()
        high_resolution.isOpened.return_value = True
        high_resolution.read.return_value = (True, mock.Mock(shape=(1080, 1920, 3)))
        with mock.patch.object(main.cv2, "VideoCapture", return_value=high_resolution):
            self.assertFalse(main.can_decode_video_first_frame("high-resolution.mp4"))
        high_resolution.release.assert_called_once()

        unreadable = mock.Mock()
        unreadable.isOpened.return_value = True
        unreadable.read.return_value = (False, None)
        with mock.patch.object(main.cv2, "VideoCapture", return_value=unreadable):
            self.assertFalse(main.can_decode_video_first_frame("unreadable.mov"))
        unreadable.release.assert_called_once()

        unopened = mock.Mock()
        unopened.isOpened.return_value = False
        with mock.patch.object(main.cv2, "VideoCapture", return_value=unopened):
            self.assertFalse(main.can_decode_video_first_frame("unsupported.mov"))
        unopened.release.assert_called_once()

    def test_upload_creation_rejects_insufficient_disk_space_before_creating_session(self):
        if not Path("/app/main.py").exists():
            self.skipTest("Run this integration test inside the backend Docker image")
        sys.path.insert(0, "/app")
        import main
        from fastapi import HTTPException
        before = set(main.match_uploads)
        with mock.patch.object(
            main, "match_upload_disk_capacity",
            return_value={"ok": False, "free_bytes": 10, "required_bytes": 100},
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main.create_match_upload({
                    "filename": "too-large-for-free-space.mp4",
                    "size_bytes": 1024,
                    "duration_seconds": 60,
                }))
        self.assertEqual(raised.exception.status_code, 507)
        self.assertEqual(set(main.match_uploads), before)

    def test_chunk_preflight_stops_without_writing_when_space_runs_out(self):
        if not Path("/app/main.py").exists():
            self.skipTest("Run this integration test inside the backend Docker image")
        sys.path.insert(0, "/app")
        import main
        from fastapi import HTTPException
        from starlette.datastructures import UploadFile

        async def run():
            with mock.patch.object(
                main, "match_upload_disk_capacity",
                return_value={"ok": True, "free_bytes": 10**9, "required_bytes": 1},
            ):
                created = await main.create_match_upload({
                    "filename": "capacity-check.mp4", "size_bytes": 1024, "duration_seconds": 60,
                })
            upload_id = created["upload_id"]
            state = main.match_uploads[upload_id]
            try:
                with mock.patch.object(
                    main, "match_upload_disk_capacity",
                    return_value={"ok": False, "free_bytes": 10, "required_bytes": 100},
                ):
                    upload = UploadFile(filename="chunk.bin", file=io.BytesIO(b"x" * 1024))
                    with self.assertRaises(HTTPException) as raised:
                        await main.upload_match_chunk(upload_id, 0, upload)
                self.assertEqual(raised.exception.status_code, 507)
                self.assertEqual(state["received_bytes"], 0)
                self.assertEqual(os.path.getsize(state["path"]), 0)
            finally:
                main.cancel_match_upload(upload_id)

        asyncio.run(run())

    def test_15_and_20_minute_chunk_receipt_and_completion(self):
        if not Path("/app/main.py").exists():
            self.skipTest("Run this integration test inside the backend Docker image")
        sys.path.insert(0, "/app")
        import main
        from fastapi import BackgroundTasks
        from starlette.datastructures import UploadFile

        async def exercise(duration_seconds, total_size, filename):
            init = await main.create_match_upload({
                "filename": filename,
                "size_bytes": total_size,
                "duration_seconds": duration_seconds,
                "jersey_numbers": "10,74",
            })
            self.assertTrue(init.get("upload_id"))
            upload_id = init["upload_id"]
            chunk_size = init["chunk_size"]
            self.assertEqual(chunk_size, 12 * 1024 * 1024)
            self.assertEqual(init["total_chunks"], (total_size + chunk_size - 1) // chunk_size)

            offset = 0
            for index in range(init["total_chunks"]):
                expected_size = min(chunk_size, total_size - offset)
                payload = bytes([index + 1]) * expected_size
                upload = UploadFile(filename=f"chunk-{index}.bin", file=io.BytesIO(payload))
                response = await main.upload_match_chunk(upload_id, index, upload)
                self.assertEqual(response["received_bytes"], offset + expected_size)
                self.assertEqual(response["total_bytes"], total_size)
                self.assertFalse(response["duplicate_retry"])

                if index == 0:
                    retry = UploadFile(filename="chunk-0-retry.bin", file=io.BytesIO(payload))
                    duplicate = await main.upload_match_chunk(upload_id, index, retry)
                    self.assertTrue(duplicate["duplicate_retry"])
                    self.assertEqual(duplicate["received_bytes"], expected_size)

                offset += expected_size

            state = main.match_uploads[upload_id]
            self.assertEqual(state["received_bytes"], total_size)
            self.assertEqual(os.path.getsize(state["path"]), total_size)
            with open(state["path"], "rb") as received:
                self.assertEqual(received.read(16), bytes([1]) * 16)
                received.seek(total_size - 16)
                self.assertEqual(received.read(16), bytes([init["total_chunks"]]) * 16)

            tasks = BackgroundTasks()
            completed = await main.complete_match_upload(upload_id, tasks)
            self.assertTrue(completed["ok"])
            self.assertEqual(completed["status"], "queued")
            self.assertIn(completed["job_id"], main.match_jobs)
            self.assertNotIn(upload_id, main.match_uploads)
            self.assertEqual(len(tasks.tasks), 1)
            self.assertEqual(main.match_jobs[completed["job_id"]]["size_bytes"], total_size)

            retry_tasks = BackgroundTasks()
            retried = await main.complete_match_upload(upload_id, retry_tasks)
            self.assertEqual(retried["job_id"], completed["job_id"])
            self.assertEqual(retried["status"], "queued")
            self.assertEqual(len(retry_tasks.tasks), 0)
            self.assertEqual(len(tasks.tasks), 1)
            os.remove(state["path"])

        async def run():
            await exercise(900, 7 * 1024 * 1024 + 11, "synthetic-15min.mp4")
            await exercise(1200, 13 * 1024 * 1024 + 123, "synthetic-20min.mp4")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
