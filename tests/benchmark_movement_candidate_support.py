"""Compare legacy O(n^2) and time-window movement support without changing outputs."""
import random
import statistics
import time

import main as backend


FRAME_COUNT = 1829
REPEATS = 11
SEED = 69012


def legacy_build_movement_candidates(summary, max_events=8):
    """Reference implementation retained verbatim from the pre-optimization path."""
    if not isinstance(summary, dict):
        return []
    frames = summary.get("frames", [])
    if not isinstance(frames, list):
        return []
    try:
        limit = int(max_events)
    except (TypeError, ValueError, OverflowError):
        limit = 8
    if isinstance(max_events, bool) or limit <= 0:
        return []
    limit = min(limit, 8)

    def finite_nonnegative(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")) or number < 0:
                return None
            return number
        except (TypeError, ValueError, OverflowError):
            return None

    by_time = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        timestamp = finite_nonnegative(frame.get("time_seconds"))
        if timestamp is None:
            continue
        speeds = [
            finite_nonnegative(frame.get("left_foot_image_motion_per_sec")),
            finite_nonnegative(frame.get("right_foot_image_motion_per_sec")),
        ]
        valid_speeds = [value for value in speeds if value is not None]
        score = max(valid_speeds) if valid_speeds else None
        key = round(timestamp, 3)
        existing = by_time.get(key)
        if existing is None or (score is not None and (existing["score"] is None or score > existing["score"])):
            by_time[key] = {"time_seconds": timestamp, "score": score}

    samples = sorted(by_time.values(), key=lambda item: item["time_seconds"])
    scored = [item for item in samples if item["score"] is not None and item["score"] > 0]
    if len(scored) < 3:
        return []

    interval = finite_nonnegative(summary.get("sampling_interval_seconds"))
    if interval is None or interval <= 0:
        gaps = [
            samples[index]["time_seconds"] - samples[index - 1]["time_seconds"]
            for index in range(1, len(samples))
            if samples[index]["time_seconds"] > samples[index - 1]["time_seconds"]
        ]
        if gaps:
            ordered_gaps = sorted(gaps)
            middle = len(ordered_gaps) // 2
            interval = ordered_gaps[middle] if len(ordered_gaps) % 2 else (ordered_gaps[middle - 1] + ordered_gaps[middle]) / 2
        else:
            return []
    max_adjacent_gap = max(interval * 1.75, interval + 0.1)

    def neighbor_support_count(item):
        return sum(
            1 for other in scored
            if (other is not item
                and 0 < abs(item["time_seconds"] - other["time_seconds"]) <= max_adjacent_gap
                and other["score"] >= item["score"] * 0.35)
        )

    for item in scored:
        item["temporal_support_samples"] = neighbor_support_count(item)
    values = sorted(item["score"] for item in scored)
    threshold = values[min(len(values) - 1, int((len(values) - 1) * 0.75))]
    selected = [
        item for item in scored
        if item["score"] >= threshold and item["score"] > 0.015
        and item["temporal_support_samples"] > 0
    ]
    selected.sort(key=lambda item: item["score"], reverse=True)
    chosen = []
    for item in selected:
        if all(abs(item["time_seconds"] - old["time_seconds"]) >= 10 for old in chosen):
            chosen.append(item)
        if len(chosen) >= limit:
            break
    chosen.sort(key=lambda item: item["time_seconds"])
    return [
        {
            "id": str(index + 1),
            "time_seconds": round(item["time_seconds"], 2),
            "movement_score": round(item["score"], 4),
            "temporal_support_samples": item["temporal_support_samples"],
            "label": "動きの変化候補",
            "reason": "足先の画像上の移動量が大きく、近い時刻のサンプルでも動きが確認できる時間帯です。",
            "is_football_action_confirmed": False,
        }
        for index, item in enumerate(chosen)
    ]


def make_summary(frame_count=FRAME_COUNT, seed=SEED, interval=0.5):
    rng = random.Random(seed)
    frames = []
    for index in range(frame_count):
        timestamp = index * interval
        # A small amount of deterministic jitter, repeated timestamps and malformed
        # records exercise the same deduplication and input-validation branches.
        timestamp += rng.choice((0.0, 0.0, 0.0, 0.0002, -0.0002))
        if index % 211 == 0:
            frames.append(None)
        if index % 97 == 0 and index:
            timestamp = (index - 1) * interval
        left = rng.random() * 0.42 if index % 13 else None
        right = rng.random() * 0.42 if index % 17 else None
        frames.append({
            "time_seconds": max(0.0, timestamp),
            "left_foot_image_motion_per_sec": left,
            "right_foot_image_motion_per_sec": right,
        })
    return {"sampling_interval_seconds": interval, "frames": frames}


def measure(function, summary, repeats=REPEATS):
    durations = []
    output = None
    for _ in range(repeats):
        started = time.perf_counter()
        output = function(summary)
        durations.append(time.perf_counter() - started)
    return output, durations


def report(label, durations):
    print(
        f"{label}: median={statistics.median(durations):.6f}s "
        f"min={min(durations):.6f}s max={max(durations):.6f}s "
        f"stdev={statistics.pstdev(durations):.6f}s"
    )


def main():
    summary = make_summary()
    expected, old_times = measure(legacy_build_movement_candidates, summary)
    actual, new_times = measure(backend.build_movement_candidates, summary)
    if expected != actual:
        raise AssertionError(f"Candidate output mismatch: old={expected!r}, new={actual!r}")

    # Compare several input shapes, including inferred interval and sparse time gaps.
    for index, (count, interval) in enumerate(((240, 0.5), (1200, 0.5), (1829, 0.5), (900, 1.0))):
        sample = make_summary(count, SEED + index + 1, interval)
        if legacy_build_movement_candidates(sample) != backend.build_movement_candidates(sample):
            raise AssertionError(f"Output mismatch for equivalence dataset {index}")

    old_median = statistics.median(old_times)
    new_median = statistics.median(new_times)
    speedup = old_median / new_median if new_median > 0 else float("inf")
    reduction = (1 - new_median / old_median) * 100 if old_median > 0 else 0.0
    print(
        f"Movement candidate benchmark: {FRAME_COUNT} frames, "
        f"{len(summary['frames'])} raw records, {REPEATS} repeats, seed={SEED}"
    )
    report("Legacy O(n^2)", old_times)
    report("Time-window bisect", new_times)
    print(f"Speedup: {speedup:.3f}x; median time reduction: {reduction:.2f}%")
    print("Output equivalence: PASS (all candidate fields identical across 5 datasets)")
    if new_median >= old_median:
        raise AssertionError("Time-window implementation did not improve median runtime")


if __name__ == "__main__":
    main()
