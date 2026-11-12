import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class VideoDecodeSamplingBenchmark(unittest.TestCase):
    def test_ffmpeg_select_matches_opencv_grab_sample_frames(self):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            self.skipTest(f"OpenCV/NumPy are provided by the backend Docker image: {exc}")

        # Short deterministic clip: 30 fps source, sample every 15 frames (2 fps).
        # This is a correctness/performance comparison, not a timing threshold test.
        with tempfile.TemporaryDirectory(prefix="riku-decode-bench-") as directory:
            video_path = str(Path(directory) / "decode-benchmark.mkv")
            generated = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=30",
                    "-an", "-c:v", "ffv1", "-level", "3", video_path,
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)

            interval = 15
            capture = cv2.VideoCapture(video_path)
            self.assertTrue(capture.isOpened())
            opencv_frames = []
            opencv_started = time.perf_counter()
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                opencv_frames.append(frame)
                for _ in range(interval - 1):
                    if not capture.grab():
                        break
                else:
                    continue
                break
            opencv_seconds = time.perf_counter() - opencv_started
            capture.release()

            ffmpeg_started = time.perf_counter()
            extracted = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", video_path,
                    "-vf", r"select=not(mod(n\,15))",
                    "-fps_mode", "passthrough", "-f", "rawvideo",
                    "-pix_fmt", "bgr24", "pipe:1",
                ],
                capture_output=True,
                timeout=90,
            )
            ffmpeg_seconds = time.perf_counter() - ffmpeg_started
            self.assertEqual(extracted.returncode, 0, extracted.stderr.decode("utf-8", "replace"))

            frame_bytes = 640 * 360 * 3
            self.assertEqual(len(extracted.stdout) % frame_bytes, 0)
            ffmpeg_frames = [
                np.frombuffer(extracted.stdout[offset:offset + frame_bytes], dtype=np.uint8)
                .reshape((360, 640, 3))
                for offset in range(0, len(extracted.stdout), frame_bytes)
            ]

            self.assertEqual(len(opencv_frames), 60)
            self.assertEqual(len(ffmpeg_frames), len(opencv_frames))
            for index, (opencv_frame, ffmpeg_frame) in enumerate(zip(opencv_frames, ffmpeg_frames)):
                self.assertTrue(
                    np.array_equal(opencv_frame, ffmpeg_frame),
                    f"Sampled frame {index} differs between OpenCV and FFmpeg",
                )

            print(
                "Decode benchmark (30s/30fps, 60 samples): "
                f"OpenCV read+grab={opencv_seconds:.3f}s; "
                f"FFmpeg select={ffmpeg_seconds:.3f}s; "
                f"frames identical={len(opencv_frames)}"
            )

    def test_opencv_random_seek_matches_sequential_on_long_gop(self):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            self.skipTest(f"OpenCV/NumPy are provided by the backend Docker image: {exc}")

        # Inter-frame MPEG-4 with a 2-second GOP is closer to phone footage than
        # the all-intra FFV1 fixture above. Compare exact decoded sample frames.
        with tempfile.TemporaryDirectory(prefix="riku-seek-bench-") as directory:
            video_path = str(Path(directory) / "long-gop-benchmark.mp4")
            generated = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=30",
                    "-an", "-c:v", "mpeg4", "-q:v", "3", "-g", "60", "-bf", "0",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)

            interval = 15
            expected_indices = list(range(0, 900, interval))

            sequential = cv2.VideoCapture(video_path)
            self.assertTrue(sequential.isOpened())
            sequential_frames = []
            sequential_started = time.perf_counter()
            for index in range(900):
                ok, frame = sequential.read()
                if not ok:
                    break
                if index % interval == 0:
                    sequential_frames.append(frame)
            sequential_seconds = time.perf_counter() - sequential_started
            sequential.release()

            seeking = cv2.VideoCapture(video_path)
            self.assertTrue(seeking.isOpened())
            seek_frames = []
            seek_started = time.perf_counter()
            seek_supported = True
            for index in expected_indices:
                if not seeking.set(cv2.CAP_PROP_POS_FRAMES, index):
                    seek_supported = False
                    break
                ok, frame = seeking.read()
                if not ok:
                    seek_supported = False
                    break
                seek_frames.append(frame)
            seek_seconds = time.perf_counter() - seek_started
            seeking.release()

            self.assertTrue(seek_supported, "OpenCV backend must support frame seeking")
            self.assertEqual(len(sequential_frames), len(expected_indices))
            self.assertEqual(len(seek_frames), len(sequential_frames))
            for index, (expected, actual) in enumerate(zip(sequential_frames, seek_frames)):
                self.assertTrue(
                    np.array_equal(expected, actual),
                    f"Random-seek sampled frame {index} differs from sequential decode",
                )

            print(
                "Long-GOP seek benchmark (30s/30fps, 60 samples): "
                f"sequential decode={sequential_seconds:.3f}s; "
                f"random seek={seek_seconds:.3f}s; "
                f"speedup={sequential_seconds / seek_seconds:.2f}x; "
                f"frames identical={len(seek_frames)}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
