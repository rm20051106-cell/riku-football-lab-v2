"""Run a full match-video pose scan locally and print detailed timing JSON.

Example (from the repository root):
  docker build -t riku-football-lab-profile ./backend
  docker run --rm --memory=2g -v "$PWD/sample.mov:/input/sample.mov:ro" \\
    -v "$PWD/backend/profile_match_video.py:/app/profile_match_video.py:ro" \\
    riku-football-lab-profile python /app/profile_match_video.py /input/sample.mov --jersey-numbers 10,74

Compare the unchanged default (8) with a capped run (4):
  docker run --rm --memory=2g -v "$PWD/sample.mov:/input/sample.mov:ro" \\
    -v "$PWD/backend/profile_match_video.py:/app/profile_match_video.py:ro" \\
    riku-football-lab-profile python /app/profile_match_video.py /input/sample.mov --compare-pose-counts

The video is mounted read-only and is not uploaded or copied into the repository.
"""
import argparse
import json
import time
from pathlib import Path

from main import process_match_video


METRIC_FIELDS = (
    "pose_geometry_seconds",
    "jersey_ocr_seconds",
    "person_track_association_seconds",
    "foot_motion_feature_seconds",
)


def profile(video, jersey_numbers, max_poses):
    started = time.monotonic()
    result = process_match_video(
        str(video), jersey_numbers=jersey_numbers, max_poses=max_poses
    )
    elapsed = time.monotonic() - started
    summary = result.get("summary", result)
    timing = summary.get("scan_timing", {})
    return {
        "max_poses": max_poses,
        "wall_clock_seconds": round(elapsed, 3),
        "duration_seconds": summary.get("duration_seconds"),
        "sampling_rate_fps": summary.get("sampling_rate_fps"),
        "sampling_interval_seconds": summary.get("sampling_interval_seconds"),
        "sampled_pose_frames": summary.get("sampled_pose_frames"),
        "video_scan_quality": summary.get("video_scan_quality", {}),
        "person_detection_summary": summary.get("person_detection_summary", {}),
        "person_track_summary": summary.get("person_track_summary", {}),
        "jersey_ocr_summary": summary.get("jersey_ocr_summary", {}),
        "scan_timing": timing,
        "required_metrics_present": {
            name: name in timing for name in METRIC_FIELDS
        },
    }


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_comparison_report(reports):
    """Compare run summaries without treating synthetic fixtures as model benchmarks."""
    normalized = []
    for report in reports:
        quality = report.get("video_scan_quality") or {}
        detection = report.get("person_detection_summary") or {}
        timing = report.get("scan_timing") or {}
        sampled_value = _number(report.get("sampled_pose_frames"))
        sampled = max(0, int(sampled_value)) if sampled_value is not None else 0

        detected_value = _number(quality.get("pose_detected_frames"))
        if detected_value is None:
            detected_value = _number(detection.get("frames_with_people"))
        detected = max(0, int(detected_value)) if detected_value is not None else 0
        # A malformed summary must not report more detected frames than samples.
        detected = min(detected, sampled)
        rate_value = _number(quality.get("pose_detection_rate"))
        rate = (max(0.0, min(1.0, float(rate_value))) if rate_value is not None
                else (round(detected / sampled, 4) if sampled else None))

        wall = _number(report.get("wall_clock_seconds"))
        inference = _number(timing.get("pose_inference_seconds"))
        people = _number(timing.get("pose_person_count"))
        normalized.append({
            "max_poses": report.get("max_poses"),
            "wall_clock_seconds": round(wall, 3) if wall is not None else None,
            "pose_inference_seconds": round(inference, 3) if inference is not None else None,
            "sampled_pose_frames": sampled,
            "pose_detected_frames": detected,
            "missed_pose_frames": sampled - detected,
            "pose_detection_rate": rate,
            "total_person_detections": int(people) if people is not None else None,
            "average_people_per_sample": _number(detection.get("average_people_per_sample")),
            "max_people_in_one_frame": _number(detection.get("max_people_in_one_frame")),
            "sampling_interval_seconds": _number(report.get("sampling_interval_seconds")),
            "fixture_only": bool(report.get("fixture_only", False)),
        })

    comparison = {}
    if len(normalized) >= 2:
        baseline, capped = normalized[0], normalized[1]
        baseline_time = baseline["wall_clock_seconds"]
        capped_time = capped["wall_clock_seconds"]
        baseline_rate, capped_rate = baseline["pose_detection_rate"], capped["pose_detection_rate"]
        baseline_people, capped_people = baseline["total_person_detections"], capped["total_person_detections"]
        comparison = {
            "baseline_max_poses": baseline["max_poses"],
            "capped_max_poses": capped["max_poses"],
            "wall_clock_seconds_saved": (
                round(baseline_time - capped_time, 3)
                if baseline_time is not None and capped_time is not None else None
            ),
            "wall_clock_reduction_percent": (
                round((baseline_time - capped_time) / baseline_time * 100, 2)
                if baseline_time is not None and capped_time is not None and baseline_time > 0 else None
            ),
            "same_sample_count": baseline["sampled_pose_frames"] == capped["sampled_pose_frames"],
            "same_sampling_interval": baseline["sampling_interval_seconds"] == capped["sampling_interval_seconds"],
            "pose_detection_rate_delta": (
                round(capped_rate - baseline_rate, 4)
                if baseline_rate is not None and capped_rate is not None else None
            ),
            "pose_detected_frames_delta": capped["pose_detected_frames"] - baseline["pose_detected_frames"],
            "total_person_detections_delta": (
                capped_people - baseline_people
                if baseline_people is not None and capped_people is not None else None
            ),
            "comparable_sampling": (
                baseline["sampled_pose_frames"] == capped["sampled_pose_frames"]
                and baseline["sampling_interval_seconds"] == capped["sampling_interval_seconds"]
            ),
            "timing_is_synthetic": all(item["fixture_only"] for item in normalized[:2]),
        }
    return {
        "runs": normalized,
        "comparison": comparison,
        "measurement_note": (
            "Synthetic fixture: validates report calculations only; elapsed values are fixture inputs, "
            "not MediaPipe or real-video performance measurements."
            if normalized and all(item["fixture_only"] for item in normalized)
            else "Elapsed time and detections are measurements from the supplied profiling runs."
        ),
    }

def main():
    parser = argparse.ArgumentParser(description="Profile a full match-video scan")
    parser.add_argument("video", help="Path to a local video file")
    parser.add_argument("--jersey-numbers", default="10,74")
    parser.add_argument("--max-poses", type=int, choices=(1, 2, 4, 8), default=8,
                        help="Maximum simultaneous pose detections; default 8 preserves production behavior")
    parser.add_argument("--compare-pose-counts", action="store_true",
                        help="Run the same video sequentially with max_poses=8 and max_poses=4")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        parser.error(f"Video file not found: {video}")

    counts = (8, 4) if args.compare_pose_counts else (args.max_poses,)
    reports = [profile(video, args.jersey_numbers, count) for count in counts]
    output = {
        "video_name": video.name,
        "comparison_mode": args.compare_pose_counts,
        **build_comparison_report(reports),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
