"""Run a full match-video pose scan locally and print detailed timing JSON.

Example (from the repository root):
  docker build -t riku-football-lab-profile ./backend
  docker run --rm --memory=2g -v "$PWD/sample.mov:/input/sample.mov:ro" \
    -v "$PWD/backend/profile_match_video.py:/app/profile_match_video.py:ro" \
    riku-football-lab-profile python /app/profile_match_video.py /input/sample.mov --jersey-numbers 10,74

Compare the unchanged default (8) with a capped run (4):
  docker run --rm --memory=2g -v "$PWD/sample.mov:/input/sample.mov:ro" \
    -v "$PWD/backend/profile_match_video.py:/app/profile_match_video.py:ro" \
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
        "runs": reports,
    }
    if len(reports) == 2:
        baseline, capped = reports
        baseline_time = baseline["wall_clock_seconds"]
        capped_time = capped["wall_clock_seconds"]
        output["comparison"] = {
            "wall_clock_speedup_8_over_4": (
                round(baseline_time / capped_time, 3) if capped_time > 0 else None
            ),
            "wall_clock_reduction_percent": (
                round((baseline_time - capped_time) / baseline_time * 100, 2)
                if baseline_time > 0 else None
            ),
            "same_sample_count": (
                baseline["sampled_pose_frames"] == capped["sampled_pose_frames"]
            ),
            "same_sampling_interval": (
                baseline["sampling_interval_seconds"] == capped["sampling_interval_seconds"]
            ),
            "detection_counts": [
                run["person_detection_summary"].get("frames_with_people")
                for run in reports
            ],
            "max_people_per_frame": [
                run["person_detection_summary"].get("max_people_in_one_frame")
                for run in reports
            ],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
