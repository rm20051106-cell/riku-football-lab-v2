"""Benchmark full-scan versus indexed candidate-window summaries.

The synthetic input mirrors a 15-minute, 2fps match scan with 1-4 detected
people per frame. It compares every returned field, not only track counts.
"""
import statistics
import time

import main as backend


FRAME_COUNT = 1829
CANDIDATE_TIMES = (14.0, 189.0, 229.0, 390.5, 460.0, 554.0, 589.5, 679.5)


def make_summary():
    frames = []
    for frame_index in range(FRAME_COUNT):
        timestamp = frame_index * 0.5
        people = []
        person_count = 1 + (frame_index % 4)
        for person_index in range(person_count):
            phase = frame_index * 0.003 + person_index * 0.17
            left = 0.08 + ((phase * 0.7 + person_index * 0.19) % 0.72)
            top = 0.12 + ((phase * 0.2 + person_index * 0.11) % 0.42)
            width = 0.12 + (person_index % 3) * 0.015
            height = 0.28 + (person_index % 2) * 0.025
            jersey = []
            if (frame_index + person_index) % 37 == 0:
                jersey = [{"number": "10" if person_index % 2 == 0 else "74"}]
            people.append({
                "person_index": person_index,
                "bbox": [round(left, 4), round(top, 4),
                         round(left + width, 4), round(top + height, 4)],
                "jersey_ocr_candidates": jersey,
            })
        frames.append({
            "time_seconds": timestamp,
            "detected_people": people,
            "detected_people_in_frame": len(people),
        })
    return {
        "duration_seconds": 914.33,
        "sampling_interval_seconds": 0.5,
        "frames": frames,
    }


def legacy_summaries(summary):
    return [
        backend.summarize_candidate_from_full_scan(summary, center, clip_duration=8.0)
        for center in CANDIDATE_TIMES
    ]


def indexed_summaries(summary):
    index = backend.build_candidate_frame_time_index(summary)
    return [
        backend.summarize_candidate_from_full_scan(
            summary, center, clip_duration=8.0, frame_index=index
        )
        for center in CANDIDATE_TIMES
    ]


def measure(function, summary, repeats=9):
    durations = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = function(summary)
        durations.append(time.perf_counter() - started)
    return result, durations


def describe(label, durations):
    print(
        f"{label}: median={statistics.median(durations):.6f}s "
        f"min={min(durations):.6f}s max={max(durations):.6f}s "
        f"stdev={statistics.pstdev(durations):.6f}s"
    )


def main():
    summary = make_summary()
    expected, old_times = measure(legacy_summaries, summary)
    actual, new_times = measure(indexed_summaries, summary)
    if expected != actual:
        raise AssertionError("Indexed candidate summaries differ from full-scan output")
    old_median = statistics.median(old_times)
    new_median = statistics.median(new_times)
    speedup = old_median / new_median if new_median > 0 else float("inf")
    improvement = (1 - new_median / old_median) * 100 if old_median > 0 else 0.0
    print(
        f"Candidate-window benchmark: {FRAME_COUNT} frames, "
        f"{len(CANDIDATE_TIMES)} candidates, 2fps, {len(old_times)} repeats"
    )
    describe("Legacy full scan", old_times)
    describe("Indexed window", new_times)
    print(f"Speedup: {speedup:.3f}x; median time reduction: {improvement:.2f}%")
    print("Output equivalence: PASS (all returned fields identical)")
    if new_median >= old_median:
        raise AssertionError("Indexed candidate-window path did not improve median runtime")


if __name__ == "__main__":
    main()
