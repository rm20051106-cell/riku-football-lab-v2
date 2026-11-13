"""Run a full match-video pose scan locally and print detailed timing JSON.

Example (from the repository root):
  docker build -t riku-football-lab-profile ./backend
  docker run --rm --memory=2g -v "$PWD/sample.mov:/input/sample.mov:ro" \
    -v "$PWD/backend/profile_match_video.py:/app/profile_match_video.py:ro" \
    riku-football-lab-profile python /app/profile_match_video.py /input/sample.mov --jersey-numbers 10,74

The video is mounted read-only and is not uploaded or copied into the repository.
"""
import argparse
import json
from pathlib import Path

from main import process_match_video


def main():
    parser = argparse.ArgumentParser(description="Profile a full match-video scan")
    parser.add_argument("video", help="Path to a local video file")
    parser.add_argument("--jersey-numbers", default="10,74")
    parser.add_argument("--max-poses", type=int, choices=(1, 2, 4, 8), default=8,
                        help="Maximum simultaneous pose detections; default 8 preserves production behavior")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        parser.error(f"Video file not found: {video}")

    result = process_match_video(
        str(video), jersey_numbers=args.jersey_numbers, max_poses=args.max_poses
    )
    summary = result.get("summary", result)
    timing = summary.get("scan_timing", {})
    fields = (
        "pose_geometry_seconds",
        "jersey_ocr_seconds",
        "person_track_association_seconds",
        "foot_motion_feature_seconds",
    )
    report = {
        "video_name": video.name,
        "max_poses": args.max_poses,
        "duration_seconds": summary.get("duration_seconds"),
        "sampling_rate_fps": summary.get("sampling_rate_fps"),
        "sampled_pose_frames": summary.get("sampled_pose_frames"),
        "video_scan_quality": summary.get("video_scan_quality", {}),
        "person_detection_summary": summary.get("person_detection_summary", {}),
        "scan_timing": timing,
        "required_metrics_present": {name: name in timing for name in fields},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
