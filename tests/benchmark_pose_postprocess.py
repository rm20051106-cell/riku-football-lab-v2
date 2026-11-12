"""Compare the legacy and cached MediaPipe landmark postprocessors.

Runs inside the backend Docker image so the optimized function is imported
from the exact backend source under test. Synthetic landmarks mimic normalized
MediaPipe Pose x/y/visibility values; no model or analysis settings are changed.
"""
import random
import statistics
import time

import main as backend


class SyntheticLandmark:
    __slots__ = ("x", "y", "z", "visibility", "presence")

    def __init__(self, x, y, visibility):
        self.x = x
        self.y = y
        self.z = 0.0
        self.visibility = visibility
        self.presence = visibility


# Normalized 33-point MediaPipe Pose skeleton, with realistic body proportions.
SKELETON = [
    (0.50, 0.12), (0.49, 0.105), (0.51, 0.105), (0.47, 0.11), (0.53, 0.11),
    (0.45, 0.15), (0.55, 0.15), (0.42, 0.23), (0.58, 0.23),
    (0.40, 0.31), (0.60, 0.31), (0.43, 0.34), (0.57, 0.34),
    (0.40, 0.49), (0.60, 0.49), (0.38, 0.64), (0.62, 0.64),
    (0.37, 0.67), (0.63, 0.67), (0.36, 0.68), (0.64, 0.68),
    (0.46, 0.52), (0.54, 0.52), (0.45, 0.70), (0.55, 0.70),
    (0.44, 0.86), (0.56, 0.86), (0.43, 0.98), (0.57, 0.98),
    (0.41, 0.99), (0.59, 0.99), (0.40, 0.97), (0.60, 0.97),
]


def legacy_analyze_task_pose(lm, image_width=1, image_height=1):
    """Pre-cache implementation retained as a benchmark reference."""
    def p(name):
        item = lm[backend.mp_pose.PoseLandmark[name].value]
        visibility = float(getattr(item, "visibility", 1.0))
        return [float(item.x), float(item.y), visibility]

    visible = sum(1 for item in lm if float(getattr(item, "visibility", 1.0)) >= 0.5)

    def visible_points(*names):
        return all(p(name)[2] >= 0.5 for name in names)

    left_knee = backend.angle(p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], p("LEFT_ANKLE")[:2], image_width, image_height) if visible_points("LEFT_HIP", "LEFT_KNEE", "LEFT_ANKLE") else None
    right_knee = backend.angle(p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], p("RIGHT_ANKLE")[:2], image_width, image_height) if visible_points("RIGHT_HIP", "RIGHT_KNEE", "RIGHT_ANKLE") else None
    left_hip = backend.angle(p("LEFT_SHOULDER")[:2], p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], image_width, image_height) if visible_points("LEFT_SHOULDER", "LEFT_HIP", "LEFT_KNEE") else None
    right_hip = backend.angle(p("RIGHT_SHOULDER")[:2], p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], image_width, image_height) if visible_points("RIGHT_SHOULDER", "RIGHT_HIP", "RIGHT_KNEE") else None

    trunk_angle = None
    if visible_points("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP"):
        shoulder_mid = [(p("LEFT_SHOULDER")[0] + p("RIGHT_SHOULDER")[0]) / 2,
                        (p("LEFT_SHOULDER")[1] + p("RIGHT_SHOULDER")[1]) / 2]
        hip_mid = [(p("LEFT_HIP")[0] + p("RIGHT_HIP")[0]) / 2,
                   (p("LEFT_HIP")[1] + p("RIGHT_HIP")[1]) / 2]
        trunk_angle = round(float(backend.np.degrees(backend.np.arctan2(abs(shoulder_mid[0] - hip_mid[0]) * image_width,
                                                                         max(1e-6, abs(shoulder_mid[1] - hip_mid[1]) * image_height)))), 1)

    metric_quality = {
        "left_knee": "measured" if left_knee is not None else "insufficient_visibility",
        "right_knee": "measured" if right_knee is not None else "insufficient_visibility",
        "left_hip": "measured" if left_hip is not None else "insufficient_visibility",
        "right_hip": "measured" if right_hip is not None else "insufficient_visibility",
        "trunk": "measured" if trunk_angle is not None else "insufficient_visibility",
    }
    names = ["LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP",
             "LEFT_KNEE", "RIGHT_KNEE", "LEFT_ANKLE", "RIGHT_ANKLE",
             "LEFT_HEEL", "RIGHT_HEEL", "LEFT_FOOT_INDEX", "RIGHT_FOOT_INDEX"]
    landmarks = {name.lower(): [round(p(name)[0], 5), round(p(name)[1], 5), round(p(name)[2], 4)]
                 for name in names}
    xs = [float(item.x) for item in lm if 0 <= float(item.x) <= 1]
    ys = [float(item.y) for item in lm if 0 <= float(item.y) <= 1]
    bbox = [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)] if xs and ys else None
    return {
        "visible_landmarks": visible,
        "measurement_source": "MediaPipe Pose Landmarker geometry",
        "metric_quality": metric_quality,
        "left_knee_angle_deg": left_knee,
        "right_knee_angle_deg": right_knee,
        "left_hip_angle_deg": left_hip,
        "right_hip_angle_deg": right_hip,
        "trunk_lean_image_angle_deg": trunk_angle,
        "landmarks": landmarks,
        "bbox": bbox,
    }


def make_frames(count=1829, seed=640360):
    rng = random.Random(seed)
    frames = []
    for _ in range(count):
        shift_x = rng.uniform(-0.035, 0.035)
        shift_y = rng.uniform(-0.018, 0.018)
        scale = rng.uniform(0.94, 1.06)
        points = []
        for index, (x, y) in enumerate(SKELETON):
            px = min(1.08, max(-0.08, 0.5 + (x - 0.5) * scale + shift_x + rng.uniform(-0.004, 0.004)))
            py = min(1.08, max(-0.08, y * scale + shift_y + rng.uniform(-0.004, 0.004)))
            # Mostly visible, with occasional partial occlusion as in match footage.
            visibility = rng.uniform(0.12, 0.48) if index in (9, 10, 17, 18, 19, 20, 29, 30) and rng.random() < 0.16 else rng.uniform(0.72, 1.0)
            points.append(SyntheticLandmark(px, py, visibility))
        frames.append(points)
    return frames


def measure(function, frames, width, height, repeats=9):
    function(frames[0], width, height)  # warm-up
    durations = []
    for _ in range(repeats):
        started = time.perf_counter()
        for landmarks in frames:
            function(landmarks, width, height)
        durations.append(time.perf_counter() - started)
    return durations


def main():
    frames = make_frames()
    width, height = 960, 540

    # Compare every returned field for every generated frame before timing.
    for index, landmarks in enumerate(frames):
        old = legacy_analyze_task_pose(landmarks, width, height)
        new = backend.analyze_task_pose(landmarks, width, height)
        if old != new:
            raise AssertionError(f"Output mismatch on synthetic frame {index}: {old!r} != {new!r}")

    old_times = measure(legacy_analyze_task_pose, frames, width, height)
    new_times = measure(backend.analyze_task_pose, frames, width, height)

    old_median = statistics.median(old_times)
    new_median = statistics.median(new_times)
    speedup = old_median / new_median if new_median else float("inf")
    reduction = (1 - new_median / old_median) * 100 if old_median else 0.0

    print(f"Pose postprocess benchmark: {len(frames)} frames/repeat, {len(old_times)} repeats, {width}x{height}")
    print("Synthetic data: 33 normalized MediaPipe landmarks/frame; seeded pose jitter and partial visibility")
    print(f"Output equivalence: PASS ({len(frames)} / {len(frames)} frames; every returned field identical)")
    print(f"Legacy seconds: median={old_median:.6f}, min={min(old_times):.6f}, max={max(old_times):.6f}, stdev={statistics.stdev(old_times):.6f}")
    print(f"Cached seconds: median={new_median:.6f}, min={min(new_times):.6f}, max={max(new_times):.6f}, stdev={statistics.stdev(new_times):.6f}")
    print(f"Median speedup: {speedup:.3f}x; median time reduction: {reduction:.1f}%")
    if new_median >= old_median:
        raise AssertionError("Cached postprocessor did not improve median runtime")


if __name__ == "__main__":
    main()
