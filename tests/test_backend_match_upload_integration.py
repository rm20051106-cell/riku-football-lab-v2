import asyncio
import io
import os
import sys
import unittest
from pathlib import Path


class MatchUploadBackendIntegrationTest(unittest.TestCase):
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
            self.assertEqual(chunk_size, 6 * 1024 * 1024)
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
            os.remove(state["path"])

        async def run():
            await exercise(900, 7 * 1024 * 1024 + 11, "synthetic-15min.mp4")
            await exercise(1200, 13 * 1024 * 1024 + 123, "synthetic-20min.mp4")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
