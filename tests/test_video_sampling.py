import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from video_sampling import read_sampled_frame


class FakeCapture:
    def __init__(self):
        self.position = -1
        self.frames = list(range(20))
    def read(self):
        self.position += 1
        return (self.position < len(self.frames),
                self.frames[self.position] if self.position < len(self.frames) else None)
    def grab(self):
        self.position += 1
        return self.position < len(self.frames)
    def retrieve(self):
        if 0 <= self.position < len(self.frames):
            return True, self.frames[self.position]
        return False, None


class VideoSamplingTests(unittest.TestCase):
    def test_first_sample_reads_frame_zero(self):
        cap = FakeCapture()
        ok, frame = read_sampled_frame(cap, 4, first_sample=True)
        self.assertTrue(ok)
        self.assertEqual(frame, 0)

    def test_next_sample_advances_exact_interval(self):
        cap = FakeCapture()
        read_sampled_frame(cap, 4, first_sample=True)
        ok, frame = read_sampled_frame(cap, 4)
        self.assertTrue(ok)
        self.assertEqual(frame, 4)

    def test_sampling_remains_sequential_for_multiple_intervals(self):
        cap = FakeCapture()
        indices = []
        ok, frame = read_sampled_frame(cap, 3, first_sample=True)
        indices.append(frame)
        for _ in range(4):
            ok, frame = read_sampled_frame(cap, 3)
            if not ok:
                break
            indices.append(frame)
        self.assertEqual(indices, [0, 3, 6, 9, 12])

    def test_stops_cleanly_at_end_of_video(self):
        cap = FakeCapture()
        cap.position = 18
        ok, frame = read_sampled_frame(cap, 3)
        self.assertFalse(ok)
        self.assertIsNone(frame)


if __name__ == "__main__":
    unittest.main()
