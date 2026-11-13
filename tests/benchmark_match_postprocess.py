"""Runtime benchmark for motion-aware chronological player-track association."""
import copy
import random

import numpy as np
import statistics
import time

import main as backend


def legacy_associate_person_tracks(frames, max_gap_seconds=9.0):
    """Create provisional short-term tracks from sparse pose detections.
    These are geometric associations, not verified player identities.
    """
    tracks = []
    next_track_id = 1

    def iou(a, b):
        if not a or not b:
            return 0.0
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        union = area_a + area_b - intersection
        return intersection / union if union > 1e-9 else 0.0

    def center(box):
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def jersey_set(person):
        return {str(x.get("number")) for x in person.get("jersey_ocr_candidates", [])
                if x.get("number")}

    for frame in frames:
        now = float(frame.get("time_seconds", 0))
        people = frame.get("detected_people", [])
        pairs = []
        for person_index, person in enumerate(people):
            box = person.get("bbox")
            if not box:
                continue
            pc = center(box)
            for track_index, track in enumerate(tracks):
                gap = now - track["last_time"]
                if gap <= 0 or gap > max_gap_seconds:
                    continue
                old_box = track["last_bbox"]
                old_center = center(old_box)
                distance = float(np.linalg.norm(np.array(pc) - np.array(old_center)))
                overlap = iou(box, old_box)
                if distance > 0.22 and overlap < 0.03:
                    continue
                current_numbers = jersey_set(person)
                previous_numbers = set(track["jersey_votes"])
                number_match = bool(current_numbers & previous_numbers)
                number_conflict = bool(current_numbers and previous_numbers and not number_match)
                if number_conflict and distance > 0.08 and overlap < 0.20:
                    continue
                size_a = max(1e-4, (box[2] - box[0]) * (box[3] - box[1]))
                size_b = max(1e-4, (old_box[2] - old_box[0]) * (old_box[3] - old_box[1]))
                size_ratio = min(size_a, size_b) / max(size_a, size_b)
                cost = distance - (0.10 * overlap) - (0.08 if number_match else 0.0) + (0.08 if number_conflict else 0.0) + (0.025 * (1 - size_ratio))
                pairs.append((cost, person_index, track_index, distance, overlap, number_match))
        used_people, used_tracks = set(), set()
        assignments = {}
        for cost, person_index, track_index, distance, overlap, number_match in sorted(pairs):
            if person_index in used_people or track_index in used_tracks:
                continue
            if cost > 0.22:
                continue
            confidence = max(0.15, min(0.85, 0.75 - distance * 1.8 + overlap * 0.35 + (0.12 if number_match else 0)))
            assignments[person_index] = (tracks[track_index], round(confidence, 2),
                                         "背番号候補＋位置" if number_match else "位置・大きさ")
            used_people.add(person_index)
            used_tracks.add(track_index)

        for person_index, person in enumerate(people):
            box = person.get("bbox")
            if not box:
                person["track_id"] = None
                person["track_confidence"] = 0.0
                person["track_method"] = "位置情報なし"
                continue
            if person_index in assignments:
                track, confidence, method = assignments[person_index]
            else:
                track = {
                    "track_id": f"T{next_track_id}",
                    "first_time": now,
                    "last_time": now,
                    "last_bbox": box,
                    "sample_count": 0,
                    "jersey_votes": {},
                    "confidence_sum": 0.0,
                }
                tracks.append(track)
                next_track_id += 1
                confidence, method = 0.35, "新規検出"
            track["last_time"] = now
            track["last_bbox"] = box
            track["sample_count"] += 1
            track["confidence_sum"] += confidence
            for number in jersey_set(person):
                track["jersey_votes"][number] = track["jersey_votes"].get(number, 0) + 1
            person["track_id"] = track["track_id"]
            person["track_confidence"] = confidence
            person["track_method"] = method

    summaries = []
    for track in tracks:
        summaries.append({
            "track_id": track["track_id"],
            "first_time_seconds": round(track["first_time"], 2),
            "last_time_seconds": round(track["last_time"], 2),
            "sample_count": track["sample_count"],
            "average_association_confidence": round(track["confidence_sum"] / max(1, track["sample_count"]), 2),
            "jersey_number_candidates": track["jersey_votes"],
        })
    return {
        "provisional_track_count": len(summaries),
        "tracks": summaries,
        "note": "約4秒間隔の検出位置・大きさ・背番号OCR候補による暫定的な関連付けです。選手の継続追跡・背番号・陸玖本人を保証せず、交差や遮蔽でIDが入れ替わる可能性があります。"
    }


def make_frames(count=1829, seed=70113):
    rng = random.Random(seed)
    frames = []
    x, y = 0.42, 0.38
    for index in range(count):
        if index % 23 == 0:
            x, y = rng.uniform(0.05, 0.85), rng.uniform(0.05, 0.65)
        else:
            x = min(0.88, max(0.02, x + rng.uniform(-0.055, 0.055)))
            y = min(0.72, max(0.02, y + rng.uniform(-0.035, 0.035)))
        person_count = 1 if index % 29 not in (0, 1, 2) else (2 if index % 29 != 0 else 4)
        people = []
        for person_index in range(person_count):
            px = min(0.9, max(0.01, x + person_index * 0.27 + rng.uniform(-0.02, 0.02)))
            py = min(0.75, max(0.01, y + person_index * 0.11 + rng.uniform(-0.02, 0.02)))
            width = 0.07 + (person_index % 2) * 0.015
            height = 0.22 + (person_index % 3) * 0.025
            jersey = [{"number": "10"}] if index % 10 == 0 and person_index == 0 else []
            people.append({
                "person_index": person_index,
                "bbox": [round(px, 4), round(py, 4), round(min(1.0, px + width), 4), round(min(1.0, py + height), 4)],
                "jersey_ocr_candidates": jersey,
            })
        frames.append({"time_seconds": index * 0.5, "detected_people": people})
    return frames


def measure(function, frames, repeats):
    timings, result = [], None
    for _ in range(repeats):
        started = time.perf_counter()
        result = function(frames)
        timings.append(time.perf_counter() - started)
    return result, timings


def report(label, timings):
    print(
        f"{label}: median={statistics.median(timings):.6f}s "
        f"min={min(timings):.6f}s max={max(timings):.6f}s "
        f"stdev={statistics.pstdev(timings):.6f}s"
    )


def main():
    frames = make_frames()
    old, old_times = measure(legacy_associate_person_tracks, frames, 5)
    new, new_times = measure(backend.associate_person_tracks, frames, 9)
    repeated = backend.associate_person_tracks(copy.deepcopy(frames))
    if new != repeated:
        raise AssertionError("Motion-aware track association is not deterministic")
    old_median, new_median = statistics.median(old_times), statistics.median(new_times)
    detections = sum(len(frame["detected_people"]) for frame in frames)
    print(f"Match track-association benchmark: {len(frames)} samples, {detections} detections")
    print(f"Motion-aware output determinism: PASS ({new['provisional_track_count']} provisional tracks)")
    report("Legacy all-track scan (5 repeats)", old_times)
    report("Active time-window scan (9 repeats)", new_times)
    print(f"Speedup: {old_median / new_median:.3f}x; median reduction: {(1-new_median/old_median)*100:.2f}%")
    if new_median >= old_median:
        raise AssertionError("Active-window track association did not improve median runtime")

    non_chronological = [dict(frame) for frame in frames[:80]]
    non_chronological[40] = {**non_chronological[40], "time_seconds": 1.0}
    fallback_a = backend.associate_person_tracks(copy.deepcopy(non_chronological))
    fallback_b = backend.associate_person_tracks(copy.deepcopy(non_chronological))
    if fallback_a != fallback_b:
        raise AssertionError("Non-chronological fallback is not deterministic")
    print("Non-chronological fallback determinism: PASS")


if __name__ == "__main__":
    main()
