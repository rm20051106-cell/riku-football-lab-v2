import os
import re
import bisect
import json
import time
import hashlib
import subprocess
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
import pytesseract
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

APP_NAME = "RIKU FOOTBALL LAB Free AI Analysis API"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))
MAX_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "60"))
MAX_MATCH_SECONDS = int(os.getenv("MAX_MATCH_VIDEO_SECONDS", "1200"))
MAX_MATCH_UPLOAD_MB = int(os.getenv("MAX_MATCH_UPLOAD_MB", "500"))
MATCH_SAMPLE_RATE = float(os.getenv("MATCH_SAMPLE_RATE", "2.0"))
MATCH_MAX_SAMPLES = int(os.getenv("MATCH_MAX_SAMPLES", "2400"))
POSE_LANDMARKER_MODEL = os.getenv("POSE_LANDMARKER_MODEL", "/app/models/pose_landmarker_lite.task")
match_jobs = {}
MATCH_UPLOAD_CHUNK_BYTES = 12 * 1024 * 1024
MATCH_UPLOAD_SESSION_TTL_SECONDS = 24 * 60 * 60
MATCH_UPLOAD_SESSION_DIR = Path(os.getenv(
    "MATCH_UPLOAD_SESSION_DIR",
    str(Path(tempfile.gettempdir()) / "riku-match-upload-sessions"),
))
MATCH_UPLOAD_SESSION_DIR.mkdir(parents=True, exist_ok=True)
MATCH_UPLOAD_DISK_RESERVE_BYTES = int(os.getenv("MATCH_UPLOAD_DISK_RESERVE_MB", "256")) * 1024 * 1024


def match_upload_disk_capacity(required_bytes):
    """Check free space on the same filesystem used for upload and FFmpeg temp files."""
    try:
        free_bytes = shutil.disk_usage(MATCH_UPLOAD_SESSION_DIR).free
    except OSError:
        return {"ok": False, "free_bytes": None, "required_bytes": required_bytes}
    return {
        "ok": free_bytes >= required_bytes,
        "free_bytes": free_bytes,
        "required_bytes": required_bytes,
    }


def match_upload_manifest_path(upload_id):
    return MATCH_UPLOAD_SESSION_DIR / (str(upload_id) + ".json")


def match_job_manifest_path(job_id):
    return MATCH_UPLOAD_SESSION_DIR / (str(job_id) + ".job.json")


def persist_match_job_state(job_id, job):
    """Atomically persist job progress and result for same-filesystem process restarts."""
    if not isinstance(job, dict):
        return
    target = match_job_manifest_path(job_id)
    temporary = target.with_suffix(".job.json.tmp")
    payload = dict(job)
    payload["updated_at"] = time.time()
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    except (OSError, TypeError, ValueError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def restore_match_jobs():
    restored = {}
    for manifest_path in MATCH_UPLOAD_SESSION_DIR.glob("*.job.json"):
        job_id = manifest_path.name[:-len(".job.json")]
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(job, dict) or job.get("job_id") != job_id:
                raise ValueError("invalid job manifest")
            status = str(job.get("status") or "")
            source_path = job.get("source_path")
            if status in {"queued", "processing"}:
                if source_path and os.path.isfile(source_path):
                    job.update(status="queued", progress=0, stage="再起動後の解析再開待ち")
                else:
                    job.update(
                        status="failed", progress=100, stage="解析を再開できません",
                        error="サーバー再起動後に元動画の一時ファイルが見つかりません。動画を再送信してください。",
                    )
            restored[job_id] = job
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            try:
                manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
    return restored


def persist_match_upload_state(upload_id, upload_state):
    """Atomically persist upload metadata beside the temporary video bytes."""
    manifest = {
        key: upload_state[key]
        for key in (
            "path", "filename", "total_size", "duration_seconds", "chunk_size",
            "total_chunks", "next_chunk", "received_bytes", "jersey_numbers",
        )
    }
    manifest["chunk_hashes"] = {
        str(index): digest for index, digest in upload_state.get("chunk_hashes", {}).items()
    }
    manifest["updated_at"] = time.time()
    target = match_upload_manifest_path(upload_id)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def restore_match_upload_sessions():
    """Restore valid, unexpired sessions after an app-process restart."""
    restored = {}
    now = time.time()
    for manifest_path in MATCH_UPLOAD_SESSION_DIR.glob("*.json"):
        # Job manifests share this directory but are restored by restore_match_jobs().
        if manifest_path.name.endswith(".job.json"):
            continue
        upload_id = manifest_path.stem
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            path = Path(manifest["path"])
            total_size = int(manifest["total_size"])
            received_bytes = int(manifest["received_bytes"])
            updated_at = float(manifest["updated_at"])
            if (now - updated_at > MATCH_UPLOAD_SESSION_TTL_SECONDS
                    or total_size <= 0 or total_size > MAX_MATCH_UPLOAD_MB * 1024 * 1024
                    or received_bytes < 0 or received_bytes > total_size
                    or not path.is_file() or path.stat().st_size < received_bytes):
                raise ValueError("expired or incomplete upload session")
            # A crash may occur after writing chunk bytes but before the manifest
            # replacement. Discard that uncommitted tail so the client can retry it.
            if path.stat().st_size > received_bytes:
                with path.open("r+b") as video:
                    video.truncate(received_bytes)
            state = {
                **manifest,
                "chunk_hashes": {int(k): v for k, v in manifest.get("chunk_hashes", {}).items()},
            }
            restored[upload_id] = state
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            try:
                manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
    return restored


match_uploads = restore_match_upload_sessions()
match_jobs = restore_match_jobs()
completed_match_uploads = {
    str(job["upload_id"]): job_id
    for job_id, job in match_jobs.items()
    if job.get("upload_id")
}
highlight_collections = {}

app = FastAPI(title=APP_NAME, version="0.1.0")
# Public demo configuration. Restrict CORS to the GitHub Pages URL after deployment.
allowed = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

mp_pose = mp.solutions.pose
LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left",
    "mouth_right", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky", "left_index",
    "right_index", "left_thumb", "right_thumb", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle", "left_heel",
    "right_heel", "left_foot_index", "right_foot_index"
]

def angle(a, b, c, image_width=1, image_height=1):
    # MediaPipe x/y are normalized independently by image width/height.
    # Convert back to pixel-space before Euclidean geometry to avoid aspect-ratio distortion.
    a = np.array([float(a[0]) * image_width, float(a[1]) * image_height], dtype=float)
    b = np.array([float(b[0]) * image_width, float(b[1]) * image_height], dtype=float)
    c = np.array([float(c[0]) * image_width, float(c[1]) * image_height], dtype=float)
    ba, bc = a - b, c - b
    denom = np.linalg.norm(ba) * np.linalg.norm(bc)
    if denom < 1e-8:
        return None
    cosine = float(np.clip(np.dot(ba, bc) / denom, -1.0, 1.0))
    return round(float(np.degrees(np.arccos(cosine))), 1)

def image_motion_per_width_per_second(a, b, dt, image_width, image_height):
    """Aspect-ratio-corrected 2D image displacement, expressed in frame-widths/second."""
    width, height, elapsed = float(image_width or 0), float(image_height or 0), float(dt or 0)
    if width <= 0 or height <= 0 or elapsed <= 0 or a is None or b is None:
        return None
    dx = (float(a[0]) - float(b[0])) * width
    dy = (float(a[1]) - float(b[1])) * height
    return round(float(np.hypot(dx, dy) / width / elapsed), 4)


def lm_point(landmarks, name):
    idx = mp_pose.PoseLandmark[name.upper()].value
    p = landmarks[idx]
    return [round(float(p.x), 5), round(float(p.y), 5), round(float(p.visibility), 4)]

def analyze_frame(frame, pose):
    image_height, image_width = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = pose.process(rgb)
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks.landmark
    def p(name):
        v = lm[mp_pose.PoseLandmark[name].value]
        return [float(v.x), float(v.y), float(v.visibility)]
    visible = sum(1 for v in lm if v.visibility >= 0.5)
    def visible_points(*names):
        return all(p(name)[2] >= 0.5 for name in names)
    left_knee = angle(p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], p("LEFT_ANKLE")[:2], image_width, image_height) if visible_points("LEFT_HIP", "LEFT_KNEE", "LEFT_ANKLE") else None
    right_knee = angle(p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], p("RIGHT_ANKLE")[:2], image_width, image_height) if visible_points("RIGHT_HIP", "RIGHT_KNEE", "RIGHT_ANKLE") else None
    left_hip = angle(p("LEFT_SHOULDER")[:2], p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], image_width, image_height) if visible_points("LEFT_SHOULDER", "LEFT_HIP", "LEFT_KNEE") else None
    right_hip = angle(p("RIGHT_SHOULDER")[:2], p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], image_width, image_height) if visible_points("RIGHT_SHOULDER", "RIGHT_HIP", "RIGHT_KNEE") else None
    trunk_angle = None
    if visible_points("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP"):
        shoulder_mid = [(p("LEFT_SHOULDER")[0] + p("RIGHT_SHOULDER")[0]) / 2,
                        (p("LEFT_SHOULDER")[1] + p("RIGHT_SHOULDER")[1]) / 2]
        hip_mid = [(p("LEFT_HIP")[0] + p("RIGHT_HIP")[0]) / 2,
                   (p("LEFT_HIP")[1] + p("RIGHT_HIP")[1]) / 2]
        trunk_dx = shoulder_mid[0] - hip_mid[0]
        trunk_dy = shoulder_mid[1] - hip_mid[1]
        trunk_angle = round(float(np.degrees(np.arctan2(abs(trunk_dx) * image_width, max(1e-6, abs(trunk_dy) * image_height)))), 1)
    metric_quality = {
        "left_knee": "measured" if left_knee is not None else "insufficient_visibility",
        "right_knee": "measured" if right_knee is not None else "insufficient_visibility",
        "left_hip": "measured" if left_hip is not None else "insufficient_visibility",
        "right_hip": "measured" if right_hip is not None else "insufficient_visibility",
        "trunk": "measured" if trunk_angle is not None else "insufficient_visibility",
    }
    landmarks = {}
    for name in ["LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP",
                 "LEFT_KNEE", "RIGHT_KNEE", "LEFT_ANKLE", "RIGHT_ANKLE",
                 "LEFT_HEEL", "RIGHT_HEEL", "LEFT_FOOT_INDEX", "RIGHT_FOOT_INDEX"]:
        landmarks[name.lower()] = [
            round(float(lm[mp_pose.PoseLandmark[name].value].x), 5),
            round(float(lm[mp_pose.PoseLandmark[name].value].y), 5),
            round(float(lm[mp_pose.PoseLandmark[name].value].visibility), 4),
        ]
    visible_points_xy = [(float(item.x), float(item.y)) for item in lm
                         if float(item.visibility) >= 0.5 and 0 <= float(item.x) <= 1 and 0 <= float(item.y) <= 1]
    person_bbox = None
    person_height_ratio = None
    if visible_points_xy:
        min_x = min(point[0] for point in visible_points_xy)
        max_x = max(point[0] for point in visible_points_xy)
        min_y = min(point[1] for point in visible_points_xy)
        max_y = max(point[1] for point in visible_points_xy)
        person_bbox = [round(min_x, 4), round(min_y, 4), round(max_x, 4), round(max_y, 4)]
        person_height_ratio = round(max_y - min_y, 4)
    return {
        "visible_landmarks": visible,
        "measurement_source": "MediaPipe Pose landmark geometry",
        "metric_quality": metric_quality,
        "left_knee_angle_deg": left_knee,
        "right_knee_angle_deg": right_knee,
        "left_hip_angle_deg": left_hip,
        "right_hip_angle_deg": right_hip,
        "trunk_lean_image_angle_deg": trunk_angle,
        "person_bbox_norm": person_bbox,
        "person_height_ratio": person_height_ratio,
        "landmarks": landmarks,
    }


def build_form_capture_quality(frames):
    """Summarize framing and metric evidence; missing or malformed samples never count as visible."""
    frames = [frame if isinstance(frame, dict) else {} for frame in frames] if isinstance(frames, (list, tuple)) else []

    def is_finite_number(value):
        if isinstance(value, bool):
            return False
        try:
            number = float(value)
            return number == number and number not in (float("inf"), float("-inf"))
        except (TypeError, ValueError, OverflowError):
            return False
    ratios = []
    for frame in frames:
        value = frame.get("person_height_ratio")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                number = float(value)
                if is_finite_number(number) and 0 < number <= 1:
                    ratios.append(number)
            except (TypeError, ValueError, OverflowError):
                pass

    def median(values):
        ordered = sorted(values)
        if not ordered:
            return None
        middle = len(ordered) // 2
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

    joint_names = ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                   "left_knee", "right_knee", "left_ankle", "right_ankle",
                   "left_heel", "right_heel", "left_foot_index", "right_foot_index"]
    joint_labels = {
        "left_shoulder": "左肩", "right_shoulder": "右肩",
        "left_hip": "左股関節", "right_hip": "右股関節",
        "left_knee": "左膝", "right_knee": "右膝",
        "left_ankle": "左足首", "right_ankle": "右足首",
        "left_heel": "左かかと", "right_heel": "右かかと",
        "left_foot_index": "左足先", "right_foot_index": "右足先",
    }
    visibility = {}
    for name in joint_names:
        # Missing, non-finite, out-of-range and low-confidence points are unobserved.
        visible_count = 0
        for frame in frames:
            landmarks = frame.get("landmarks")
            if not isinstance(landmarks, dict):
                continue
            point = landmarks.get(name)
            if not isinstance(point, (list, tuple)) or len(point) < 3:
                continue
            try:
                raw_x, raw_y, raw_confidence = point[0], point[1], point[2]
                if any(isinstance(value, bool) for value in (raw_x, raw_y, raw_confidence)):
                    continue
                confidence = float(raw_confidence)
                x, y = float(raw_x), float(raw_y)
                if (is_finite_number(confidence) and is_finite_number(x) and is_finite_number(y)
                        and 0 <= x <= 1 and 0 <= y <= 1 and confidence >= 0.5):
                    visible_count += 1
            except (TypeError, ValueError, OverflowError):
                continue
        visibility[name] = round(visible_count / len(frames), 3) if frames else None

    metric_fields = {
        "left_knee": "left_knee_angle_deg",
        "right_knee": "right_knee_angle_deg",
        "left_hip": "left_hip_angle_deg",
        "right_hip": "right_hip_angle_deg",
        "trunk": "trunk_lean_image_angle_deg",
        "left_foot_motion": "left_foot_image_motion_per_sec",
        "right_foot_motion": "right_foot_image_motion_per_sec",
    }
    metric_coverage = {}
    for metric, field in metric_fields.items():
        count = 0
        for frame in frames:
            value = frame.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    count += int(is_finite_number(value))
                except (TypeError, ValueError, OverflowError):
                    pass
        metric_coverage[metric] = {
            "measured_samples": count,
            "coverage_rate": round(count / len(frames), 3) if frames else None,
        }

    median_height = median(ratios)
    low_visibility = [name for name in joint_names
                      if visibility[name] is not None and visibility[name] < 0.5]
    critical_joints = ["left_hip", "right_hip", "left_knee", "right_knee",
                       "left_ankle", "right_ankle", "left_foot_index", "right_foot_index"]
    critical_rates = [visibility[name] for name in critical_joints if visibility[name] is not None]
    severe_count = sum(rate < 0.2 for rate in critical_rates)

    if len(ratios) < 3:
        status = "insufficient_samples"
        guidance = "人物サイズを安定して評価できません。全身が映る動画を撮り直してください。"
    elif median_height < 0.25:
        status = "retake_recommended_subject_too_small"
        guidance = "選手が小さく映っています。カメラを近づけ、頭から足先まで画面に入れて撮り直してください。"
    elif len(critical_rates) >= 6 and severe_count >= 3:
        status = "retake_recommended_joint_visibility"
        guidance = "股関節・膝・足首・足先の複数箇所が十分に映っていません。カメラ位置と全身の画角を調整して撮り直してください。"
    elif low_visibility:
        status = "usable_with_caution_joint_visibility"
        labels = "、".join(joint_labels[name] for name in low_visibility)
        guidance = "一部の関節が動画内で十分に確認できません（" + labels + "）。該当する角度・移動量は未計測として慎重に扱ってください。"
    elif median_height < 0.40:
        status = "usable_with_caution_subject_small"
        guidance = "選手がやや小さく映っています。動作確認はできますが、関節角度の数値は慎重に扱ってください。"
    else:
        status = "usable_for_review"
        guidance = "人物サイズと関節の可視性は確認用の目安を満たしています。撮影角度による奥行きの制限は残ります。"

    return {
        "status": status,
        "sampled_pose_frames": len(frames),
        "valid_person_size_samples": len(ratios),
        "median_person_height_ratio": round(median_height, 3) if median_height is not None else None,
        "joint_visibility_rate": visibility,
        "low_visibility_joints": low_visibility,
        "metric_sample_coverage": metric_coverage,
        "guidance": guidance,
        "note": "可視率は全サンプルを分母にし、欠測・画面外・不正値を未観測として扱います。これは撮影・計測証拠の品質目安であり、フォームの良否や測定精度の証明ではありません。",
    }


def read_jersey_number(frame, landmarks, target_numbers):
    """Read likely shirt-number text from the detected pose torso crop.
    OCR is a candidate signal, never proof of player identity.
    """
    try:
        required = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
        if not all(name in landmarks for name in required):
            return []
        h, w = frame.shape[:2]
        ls, rs = landmarks["left_shoulder"], landmarks["right_shoulder"]
        lh, rh = landmarks["left_hip"], landmarks["right_hip"]
        if min(ls[2], rs[2], lh[2], rh[2]) < 0.45:
            return []
        shoulder_width = abs(ls[0] - rs[0]) * w
        if shoulder_width < 12:
            return []
        center_x = (ls[0] + rs[0] + lh[0] + rh[0]) * w / 4
        top = int(max(0, min(ls[1], rs[1]) * h - shoulder_width * 0.12))
        bottom = int(min(h, max(lh[1], rh[1]) * h))
        half_width = int(shoulder_width * 0.95)
        left = max(0, int(center_x - half_width))
        right = min(w, int(center_x + half_width))
        if bottom - top < 12 or right - left < 12:
            return []
        crop = frame[top:bottom, left:right]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        enlarged = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        enlarged = cv2.GaussianBlur(enlarged, (3, 3), 0)
        _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        config = "--psm 6 -c tessedit_char_whitelist=0123456789"
        data = pytesseract.image_to_data(binary, config=config, output_type=pytesseract.Output.DICT)
        found = []
        targets = {str(x).strip() for x in target_numbers if str(x).strip()}
        for raw, confidence in zip(data.get("text", []), data.get("conf", [])):
            digits = re.findall(r"(?<!\d)\d{1,2}(?!\d)", str(raw))
            try:
                conf = float(confidence)
            except (TypeError, ValueError):
                continue
            for number in digits:
                if number in targets and conf >= 35:
                    found.append({"number": number, "confidence": round(conf, 1)})
        return found
    except Exception:
        return []


def camera_angle_guidance(camera_angle: str):
    guidance = {
        "右側から": [
            "選手の右側から撮影。助走、軸足を置く位置、蹴り脚の前後スイング、体幹の前後傾を確認しやすい角度です。",
            "身体の反対側に隠れる関節や左右方向の奥行きは断定できません。"
        ],
        "左側から": [
            "選手の左側から撮影。助走、軸足を置く位置、蹴り脚の前後スイング、体幹の前後傾を確認しやすい角度です。",
            "身体の反対側に隠れる関節や左右方向の奥行きは断定できません。"
        ],
        "斜め右後ろから": [
            "選手の右後方から斜めに撮影。軸足の置き位置、蹴り脚の振り抜き、骨盤・肩の回転を確認しやすい角度です。",
            "ボールとの実距離や足とボールの接触位置は自動測定できません。"
        ],
        "斜め左後ろから": [
            "選手の左後方から斜めに撮影。軸足の置き位置、蹴り脚の振り抜き、骨盤・肩の回転を確認しやすい角度です。",
            "ボールとの実距離や足とボールの接触位置は自動測定できません。"
        ],
        "後ろから": [
            "選手の真後ろから撮影。左右の脚の膝・股関節の見え方、左右の姿勢差を確認しやすい角度です。",
            "助走の前後方向、軸足とボールの距離、足とボールの接触位置は断定できません。",
            "左右の脚が重なる・隠れる場合は、その側の角度を未計測として扱います。"
        ],
        # Legacy labels remain readable for previously saved records.
        "横から": [
            "旧形式の横から撮影。助走、軸足、蹴り脚の前後スイングを確認しやすい角度です。",
            "左右の膝の向きや身体の左右差は判断しにくい場合があります。"
        ],
        "斜め後ろから": [
            "旧形式の斜め後ろから撮影。軸足と蹴り脚の振り抜きを確認しやすい角度です。",
            "左右どちら側からの撮影かは記録から特定できません。"
        ],
        "正面から": [
            "旧形式の正面から撮影。左右の足幅、膝の向き、体幹の左右への傾きを確認しやすい角度です。",
            "奥行き方向の軸足とボールの距離は判断しにくい角度です。"
        ],
        "斜め前から": [
            "旧形式の斜め前から撮影。上半身・骨盤の向きと蹴り足の通り道を確認しやすい角度です。",
            "身体で足元が隠れる瞬間があるため、接触位置は断定できません。"
        ],
    }
    return guidance.get(camera_angle, [
        "撮影角度が未指定です。全身とボールが映る動画で、5つの標準視点のいずれかから撮影すると比較しやすくなります。"
    ])

def analyze_task_pose(lm, image_width=1, image_height=1):
    landmark_data = [
        (float(item.x), float(item.y), float(getattr(item, "visibility", 1.0)))
        for item in lm
    ]
    point_cache = {}

    def p(name):
        if name not in point_cache:
            point_index = mp_pose.PoseLandmark[name].value
            point_cache[name] = landmark_data[point_index]
        return point_cache[name]

    visible = sum(1 for _, _, visibility in landmark_data if visibility >= 0.5)
    def visible_points(*names):
        return all(p(name)[2] >= 0.5 for name in names)
    left_knee = angle(p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], p("LEFT_ANKLE")[:2], image_width, image_height) if visible_points("LEFT_HIP", "LEFT_KNEE", "LEFT_ANKLE") else None
    right_knee = angle(p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], p("RIGHT_ANKLE")[:2], image_width, image_height) if visible_points("RIGHT_HIP", "RIGHT_KNEE", "RIGHT_ANKLE") else None
    left_hip = angle(p("LEFT_SHOULDER")[:2], p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], image_width, image_height) if visible_points("LEFT_SHOULDER", "LEFT_HIP", "LEFT_KNEE") else None
    right_hip = angle(p("RIGHT_SHOULDER")[:2], p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], image_width, image_height) if visible_points("RIGHT_SHOULDER", "RIGHT_HIP", "RIGHT_KNEE") else None
    trunk_angle = None
    if visible_points("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP"):
        shoulder_mid = [(p("LEFT_SHOULDER")[0] + p("RIGHT_SHOULDER")[0]) / 2,
                        (p("LEFT_SHOULDER")[1] + p("RIGHT_SHOULDER")[1]) / 2]
        hip_mid = [(p("LEFT_HIP")[0] + p("RIGHT_HIP")[0]) / 2,
                   (p("LEFT_HIP")[1] + p("RIGHT_HIP")[1]) / 2]
        trunk_angle = round(float(np.degrees(np.arctan2(abs(shoulder_mid[0] - hip_mid[0]) * image_width,
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
    xs = [x for x, _, _ in landmark_data if 0 <= x <= 1]
    ys = [y for _, y, _ in landmark_data if 0 <= y <= 1]
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



def associate_person_tracks(frames, max_gap_seconds=9.0):
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

def has_adjacent_sample_timing(current_time, previous_time, sampling_interval):
    """Reject motion comparisons spanning missing samples or invalid timestamps."""
    values = (current_time, previous_time, sampling_interval)
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        if number != number or number in (float("inf"), float("-inf")):
            return False
        numbers.append(number)
    current, previous, interval = numbers
    if interval <= 0 or current <= previous:
        return False
    gap = current - previous
    return gap <= max(interval * 1.75, interval + 0.1)


def build_match_sampling_plan(fps, total_frames, target_rate=None, max_samples=None):
    """Return a bounded, duration-aware sampling plan for a complete match video."""
    def finite_number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                return None
            return number
        except (TypeError, ValueError, OverflowError):
            return None

    rate = finite_number(target_rate)
    if rate is None or rate <= 0:
        rate = finite_number(MATCH_SAMPLE_RATE)
    if rate is None or rate <= 0:
        rate = 1.0
    rate = min(2.0, max(0.1, rate))

    limit_value = finite_number(max_samples)
    if limit_value is None or limit_value <= 0:
        limit_value = finite_number(MATCH_MAX_SAMPLES)
    if limit_value is None or limit_value <= 0:
        limit_value = 2400
    limit = max(1, min(2400, int(limit_value)))

    frame_rate = finite_number(fps)
    if frame_rate is not None and frame_rate > 0:
        # Round upward so sampling never exceeds the requested maximum rate.
        interval = max(1, int(frame_rate / rate))
        if interval * rate < frame_rate:
            interval += 1
        actual_interval = interval / frame_rate
    else:
        interval = 1
        actual_interval = 1.0

    frame_count = finite_number(total_frames)
    estimated_samples = (
        int((int(frame_count) + interval - 1) // interval)
        if frame_count is not None and frame_count > 0 else None
    )

    # Do not trust container frame-count metadata as an EOF signal. Keep the
    # configured safety ceiling and let VideoCapture.read() detect the real end.
    return {
        "frame_interval": interval,
        "sampling_interval_seconds": round(actual_interval, 3),
        "sampling_rate_fps": round(1 / actual_interval, 3) if actual_interval > 0 else None,
        "sample_limit": limit,
        "estimated_samples": estimated_samples,
    }


def iter_sampled_video_frames(capture, frame_interval, max_samples, timing_stats=None):
    import time  # Keep this function self-contained for extracted iterator tests.
    """Yield evenly spaced frames and optionally measure decode versus skipped-frame costs."""
    interval = max(1, int(frame_interval)) if not isinstance(frame_interval, bool) else 1
    limit = max(0, int(max_samples)) if not isinstance(max_samples, bool) else 0
    sample_index = 0
    while sample_index < limit:
        started = time.monotonic()
        ok, frame = capture.read()
        if timing_stats is not None:
            timing_stats["sampled_frame_decode_seconds"] += time.monotonic() - started
        if not ok:
            return
        frame_index = sample_index * interval
        sample_index += 1
        yield frame_index, frame
        for _ in range(interval - 1):
            started = time.monotonic()
            grabbed = capture.grab()
            if timing_stats is not None:
                timing_stats["skipped_frame_grab_seconds"] += time.monotonic() - started
                if grabbed:
                    timing_stats["skipped_frames_decoded"] += 1
            if not grabbed:
                return


def should_run_match_jersey_ocr(sample_index, every=10):
    """Throttle expensive shirt OCR while retaining repeated identity candidates."""
    try:
        index = int(sample_index)
        cadence = max(1, int(every))
    except (TypeError, ValueError, OverflowError):
        return False
    return index > 0 and (index == 1 or index % cadence == 0)


def process_match_video(path: str, progress_callback=None, jersey_numbers=None):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="動画を開けませんでした。MP4など一般的な形式でお試しください。")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0
    if duration > MAX_MATCH_SECONDS:
        cap.release()
        raise HTTPException(status_code=413, detail=f"試合動画は{MAX_MATCH_SECONDS}秒以内にしてください。")
    if not os.path.exists(POSE_LANDMARKER_MODEL):
        cap.release()
        raise HTTPException(status_code=503, detail="複数選手検出モデルが見つかりません。サーバーの再デプロイが必要です。")
    sampling_plan = build_match_sampling_plan(fps, total_frames)
    interval = sampling_plan["frame_interval"]
    actual_interval = sampling_plan["sampling_interval_seconds"]
    sample_limit = sampling_plan["sample_limit"]
    targets = [x.strip() for x in (jersey_numbers or "10,74").replace("；", ",").split(",") if x.strip()]
    frames, people_per_frame, jersey_counts = [], [], {}
    scan_timing = {
        "sampled_frame_decode_seconds": 0.0,
        "skipped_frame_grab_seconds": 0.0,
        "skipped_frames_decoded": 0,
        "resize_seconds": 0.0,
        "image_preparation_seconds": 0.0,
        "pose_inference_seconds": 0.0,
        "landmark_postprocess_seconds": 0.0,
    }
    pose_inference_latencies = []
    sample_index = 0
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=POSE_LANDMARKER_MODEL),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=8,
        min_pose_detection_confidence=0.35,
        min_pose_presence_confidence=0.35,
        min_tracking_confidence=0.35,
    )
    try:
        with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
            for current_frame_idx, frame in iter_sampled_video_frames(cap, interval, sample_limit, scan_timing):
                sample_index += 1
                stage_started = time.monotonic()
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, max(1, int(round(h * 960 / w)))), interpolation=cv2.INTER_AREA)
                scan_timing["resize_seconds"] += time.monotonic() - stage_started
                stage_started = time.monotonic()
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                scan_timing["image_preparation_seconds"] += time.monotonic() - stage_started
                timestamp_ms = int((current_frame_idx / fps if fps > 0 else sample_index * actual_interval) * 1000)
                stage_started = time.monotonic()
                detected = landmarker.detect_for_video(mp_image, timestamp_ms)
                inference_elapsed = time.monotonic() - stage_started
                scan_timing["pose_inference_seconds"] += inference_elapsed
                pose_inference_latencies.append(inference_elapsed)
                stage_started = time.monotonic()
                people = []
                person_metrics = []
                time_seconds = round(current_frame_idx / fps, 2) if fps > 0 else round(sample_index * actual_interval, 2)
                detected_count = len(detected.pose_landmarks or [])
                for person_index, pose_lm in enumerate(detected.pose_landmarks or []):
                    metrics = analyze_task_pose(pose_lm, frame.shape[1], frame.shape[0])
                    ocr = read_jersey_number(frame, metrics["landmarks"], targets) if should_run_match_jersey_ocr(sample_index) else []
                    for item in ocr:
                        jersey_counts[item["number"]] = jersey_counts.get(item["number"], 0) + 1
                    people.append({
                        "person_index": person_index,
                        "visible_landmarks": metrics["visible_landmarks"],
                        "bbox": metrics["bbox"],
                        "jersey_ocr_candidates": ocr,
                        "identity_status": "unverified",
                        "identity_note": "背番号OCR・位置追跡は候補情報です。本人確認は手動で行ってください。",
                        "pose_measurements": {
                            "left_knee_angle_deg": metrics.get("left_knee_angle_deg"),
                            "right_knee_angle_deg": metrics.get("right_knee_angle_deg"),
                            "left_hip_angle_deg": metrics.get("left_hip_angle_deg"),
                            "right_hip_angle_deg": metrics.get("right_hip_angle_deg"),
                            "trunk_lean_image_angle_deg": metrics.get("trunk_lean_image_angle_deg"),
                            "metric_quality": metrics.get("metric_quality", {}),
                        },
                    })
                    metrics["jersey_ocr_candidates"] = ocr
                    metrics["person_index"] = person_index
                    metrics["time_seconds"] = time_seconds
                    metrics["detected_people_in_frame"] = detected_count
                    person_metrics.append(metrics)
                people_per_frame.append(detected_count)
                scan_timing["landmark_postprocess_seconds"] += time.monotonic() - stage_started
                if person_metrics:
                    primary = max(person_metrics, key=lambda x: x["visible_landmarks"])
                    primary["detected_people"] = people
                    frames.append(primary)
                if progress_callback and duration > 0:
                    progress_callback(min(90, 15 + int(75 * min(1.0, (current_frame_idx / fps if fps > 0 else sample_index * actual_interval) / duration))))
            # If metadata understated the duration, never silently call a capped partial scan complete.
            if sample_index >= sample_limit and cap.grab():
                raise HTTPException(status_code=413, detail=f"試合動画は{MAX_MATCH_SECONDS}秒以内にしてください。")

    finally:
        cap.release()
    if not frames:
        raise HTTPException(status_code=422, detail="複数選手の姿勢を検出できませんでした。人物全身が見える明るい動画で再試行してください。")
    # Motion candidates are calculated only when a single person was detected in adjacent samples;
    # this avoids pretending that different players are one continuous track.
    for i, current in enumerate(frames):
        for side in ("left", "right"):
            key = side + "_foot_index"
            prev = frames[i - 1] if i > 0 else None
            a = current.get("landmarks", {}).get(key)
            b = prev.get("landmarks", {}).get(key) if prev else None
            dt = current.get("time_seconds", 0) - prev.get("time_seconds", 0) if prev else 0
            unique_person = current.get("detected_people_in_frame") == 1 and prev and prev.get("detected_people_in_frame") == 1
            adjacent_sample = has_adjacent_sample_timing(
                current.get("time_seconds"), prev.get("time_seconds"), actual_interval
            ) if prev else False
            if unique_person and adjacent_sample and a and b and a[2] >= 0.5 and b[2] >= 0.5:
                current[side + "_foot_image_motion_per_sec"] = image_motion_per_width_per_second(a, b, dt, frame.shape[1], frame.shape[0])
            else:
                current[side + "_foot_image_motion_per_sec"] = None
    if pose_inference_latencies:
        scan_timing["pose_inference_sample_count"] = len(pose_inference_latencies)
        scan_timing["pose_inference_p50_seconds"] = round(float(np.percentile(pose_inference_latencies, 50)), 4)
        scan_timing["pose_inference_p95_seconds"] = round(float(np.percentile(pose_inference_latencies, 95)), 4)
        scan_timing["pose_inference_max_seconds"] = round(float(max(pose_inference_latencies)), 4)
    track_summary = associate_person_tracks(frames, max_gap_seconds=max(9.0, actual_interval * 2.1))
    knees = [x[k] for x in frames for k in ("left_knee_angle_deg", "right_knee_angle_deg") if x.get(k) is not None]
    hips = [x[k] for x in frames for k in ("left_hip_angle_deg", "right_hip_angle_deg") if x.get(k) is not None]
    trunks = [x["trunk_lean_image_angle_deg"] for x in frames if x.get("trunk_lean_image_angle_deg") is not None]
    summary = {
        "sampled_pose_frames": len(frames),
        "video_scan_quality": build_video_scan_quality(sample_index, sum(1 for count in people_per_frame if count > 0)),
        "duration_seconds": round(duration, 2),
        "average_left_right_knee_angle_deg": round(float(np.mean(knees)), 1) if knees else None,
        "average_trunk_lean_image_angle_deg": round(float(np.mean(trunks)), 1) if trunks else None,
        "average_left_right_hip_angle_deg": round(float(np.mean(hips)), 1) if hips else None,
        "sampling_interval_seconds": round(actual_interval, 3),
        "sampling_rate_fps": round(1 / actual_interval, 2) if actual_interval > 0 else None,
        "scan_timing": {
            key: (
                round(value, 4)
                if key in {
                    "pose_inference_p50_seconds",
                    "pose_inference_p95_seconds",
                    "pose_inference_max_seconds",
                }
                else round(value, 2) if isinstance(value, float) else value
            )
            for key, value in scan_timing.items()
        },
        "frames": frames,
        "person_track_summary": track_summary,
        "person_detection_summary": {
            "frames_with_people": sum(1 for n in people_per_frame if n > 0),
            "average_people_per_sample": round(float(np.mean(people_per_frame)), 2) if people_per_frame else 0,
            "max_people_in_one_frame": max(people_per_frame) if people_per_frame else 0,
            "note": "MediaPipe Pose Landmarkerの複数姿勢検出結果です。人物IDの継続追跡や陸玖本人の特定を保証しません。"
        },
        "jersey_ocr_summary": {
            "candidate_detection_counts": jersey_counts,
            "note": "検出された各人物の胴体領域から読み取った背番号候補です。読み間違いがあり、本人確認ではありません。"
        },
        "evidence_policy": {
            "ai_measured": ["姿勢ランドマーク", "可視性条件を満たした膝・股関節・体幹の画像上角度", "背番号OCR候補", "暫定的な位置関連付け"],
            "manual_confirmation_required": ["陸玖本人の特定", "実際のポジション", "受ける前の首振り・周囲確認", "サポート角度・スペースへの動き出し", "プレー選択肢と判断の質", "プレー結果"],
            "not_inferred": True,
            "note": "AI検出値は個人識別・戦術評価の確定情報ではありません。本人確認済みの場面と手動評価だけを成長集計へ使用してください。"
        },
    }
    return {"ok": True, "mode": "match", "engine": "MediaPipe Pose Landmarker multi-pose + Tesseract OCR", "summary": summary}


def build_kick_phase_candidates(frames, sampling_interval_seconds, preferred_foot="right"):
    """Return conservative image-motion time candidates, never definitive kick phases."""
    try:
        interval = float(sampling_interval_seconds or 0)
    except (TypeError, ValueError, OverflowError):
        interval = 0.0
    if not np.isfinite(interval) or interval <= 0:
        interval = 0.0
    preferred_foot = preferred_foot if preferred_foot in ("left", "right") else "right"
    result = {
        "sampling_interval_seconds": round(interval, 3),
        "sampling_rate_fps": round(1 / interval, 2) if interval > 0 else None,
        "preferred_kicking_foot": preferred_foot,
        "preferred_foot_note": "右足キックを重点確認する初期設定です。反対足の候補も同じ条件で保持し、本人・蹴り足は撮影者が確認してください。" if preferred_foot == "right" else "左足キックを重点確認する初期設定です。反対足の候補も同じ条件で保持し、本人・蹴り足は撮影者が確認してください。",
        "method": "foot_index landmark image-coordinate motion with adjacent-frame support check",
        "limitations": [
            "画像上の足先移動候補であり、実空間速度・ボール接触・キック成功を示しません。",
            "助走・軸足接地・インパクトは骨格点だけでは確定できず、目視確認が必要です。",
            "カメラ移動・遠近・足先の遮蔽・別人物への検出切替で候補時刻がずれる場合があります。",
            "単独フレームだけの急な移動量は誤検出の可能性があるため、隣接サンプルの裏付けがないピークは候補にしません。",
        ],
        "feet": {},
    }
    for side in ("left", "right"):
        valid = []
        for index, frame in enumerate(frames):
            speed = frame.get(side + "_foot_image_motion_per_sec")
            timestamp = frame.get("time_seconds")
            numeric_speed = isinstance(speed, (int, float)) and not isinstance(speed, bool)
            numeric_time = isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
            if (numeric_speed and numeric_time and np.isfinite(speed) and np.isfinite(timestamp)
                    and float(speed) >= 0):
                valid.append({"frame_index": index, "time_seconds": round(float(timestamp), 3),
                              "image_motion_per_sec": round(float(speed), 5)})
        foot_result = {"sample_count": len(valid), "peak_candidate": None,
                       "post_peak_candidate": None, "opposite_foot_relative_stability": None,
                       "peak_support_samples": 0, "status": "insufficient_sampling"}
        if 0 < interval <= 0.75 and len(valid) >= 4:
            peak = max(valid, key=lambda item: item["image_motion_per_sec"])
            peak_speed = peak["image_motion_per_sec"]
            max_neighbor_gap = max(interval * 1.75, interval + 0.1)
            adjacent = [item for item in valid
                        if abs(item["frame_index"] - peak["frame_index"]) == 1
                        and 0 < abs(item["time_seconds"] - peak["time_seconds"]) <= max_neighbor_gap
                        and ((item["frame_index"] < peak["frame_index"]
                              and item["time_seconds"] < peak["time_seconds"])
                             or (item["frame_index"] > peak["frame_index"]
                                 and item["time_seconds"] > peak["time_seconds"]))]
            support = [item for item in adjacent
                       if peak_speed > 0 and item["image_motion_per_sec"] >= peak_speed * 0.35]
            foot_result["peak_support_samples"] = len(support)
            if peak_speed > 0 and support:
                foot_result["peak_candidate"] = {
                    "time_seconds": peak["time_seconds"],
                    "image_motion_per_sec": peak_speed,
                    "frame_index": peak["frame_index"],
                    "peak_support_samples": len(support),
                    "label": "隣接サンプルの裏付けがある蹴り脚の動きのピーク候補",
                }
                later = [item for item in valid
                         if item["frame_index"] > peak["frame_index"]
                         and item["time_seconds"] > peak["time_seconds"]]
                slowing = next((item for item in later
                                if item["image_motion_per_sec"] <= peak_speed * 0.7), None)
                if slowing:
                    foot_result["post_peak_candidate"] = {
                        "time_seconds": slowing["time_seconds"],
                        "image_motion_per_sec": slowing["image_motion_per_sec"],
                        "frame_index": slowing["frame_index"],
                        "label": "ピーク後に移動量が低下した候補",
                    }
                opposite = "right" if side == "left" else "left"
                peak_frame = frames[peak["frame_index"]]
                opposite_speed = peak_frame.get(opposite + "_foot_image_motion_per_sec")
                if isinstance(opposite_speed, (int, float)) and np.isfinite(opposite_speed):
                    foot_result["opposite_foot_relative_stability"] = {
                        "image_motion_per_sec": round(float(opposite_speed), 5),
                        "relative_to_peak": round(float(opposite_speed) / peak_speed, 3) if peak_speed > 0 else None,
                        "label": "反対足の移動量参考値（軸足接地の確定ではありません）",
                    }
                foot_result["status"] = "candidate_only"
            else:
                foot_result["status"] = "insufficient_peak_support"
        result["feet"][side] = foot_result
    focus = result["feet"][preferred_foot]
    result["preferred_foot_peak_candidate"] = focus.get("peak_candidate")
    result["preferred_foot_follow_through_candidate"] = focus.get("post_peak_candidate")
    result["opposite_foot_candidate"] = result["feet"]["left" if preferred_foot == "right" else "right"].get("peak_candidate")
    result["phases"] = [
        {"key": "approach", "label": "助走", "status": "manual_review_required", "time_seconds": None},
        {"key": "plant", "label": "軸足接地", "status": "manual_review_required", "time_seconds": None},
        {"key": "swing", "label": "蹴り脚の振り出し", "status": "candidate_only" if focus.get("peak_candidate") else "manual_review_required",
         "time_source": "preferred_foot_peak" if focus.get("peak_candidate") else None, "foot": preferred_foot},
        {"key": "impact", "label": "インパクト", "status": "manual_review_required", "time_seconds": None},
        {"key": "follow_through", "label": "フォロースルー", "status": "candidate_only" if focus.get("post_peak_candidate") else "manual_review_required",
         "time_source": "preferred_foot_post_peak_drop" if focus.get("post_peak_candidate") else None, "foot": preferred_foot},
    ]
    if interval > 0.75:
        result["limitations"].append("撮影・解析サンプル間隔が粗いため、動作ピーク候補を表示していません。")
    return result

def build_video_scan_quality(sampled_video_frames, pose_detected_frames):
    """Report how often pose inference found a person in frames actually sampled."""
    def safe_count(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        try:
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")) or number < 0:
                return 0
            return int(number)
        except (TypeError, ValueError, OverflowError):
            return 0

    sampled = safe_count(sampled_video_frames)
    detected = min(sampled, safe_count(pose_detected_frames))
    missed = sampled - detected
    rate = round(detected / sampled, 3) if sampled else None
    if sampled == 0 or detected < 3:
        status = "insufficient_samples"
        guidance = "姿勢を確認できたサンプルが不足しています。人物全身が映る明るい動画で撮り直してください。"
    elif rate < 0.25:
        status = "retake_recommended_low_detection"
        guidance = "サンプリングした映像の多くで姿勢を検出できません。人物の大きさ・明るさ・遮蔽を確認して撮り直してください。"
    elif rate < 0.6:
        status = "usable_with_caution_low_detection"
        guidance = "姿勢を検出できない場面が多くあります。動作候補や平均値は映った場面に偏る可能性があります。"
    else:
        status = "usable_for_review"
        guidance = "サンプリングした映像の姿勢検出率は確認用の目安を満たしています。本人識別やプレー内容の確定を意味しません。"
    return {
        "status": status,
        "sampled_video_frames": sampled,
        "pose_detected_frames": detected,
        "missed_pose_frames": missed,
        "pose_detection_rate": rate,
        "guidance": guidance,
        "note": "検出率はサンプリングしたフレーム内の姿勢検出割合です。人物本人の識別、プレー認識、撮影全時間の連続検出を保証しません。",
    }


def process_video(path: str, mode: str, camera_angle: str = "未選択", progress_callback=None, jersey_numbers=None, preferred_foot: str = "right"):
    if mode == "match":
        return process_match_video(path, progress_callback=progress_callback, jersey_numbers=jersey_numbers)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="動画を開けませんでした。MP4など一般的な形式でお試しください。")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0
    allowed_seconds = MAX_MATCH_SECONDS if mode == "match" else MAX_SECONDS
    if duration > allowed_seconds:
        cap.release()
        raise HTTPException(status_code=413, detail=f"動画が長すぎます。{mode}解析は{allowed_seconds}秒以内にしてください。")
    # Match mode scans the full match at a light sampling rate; form mode stays dense.
    target_sample_rate = MATCH_SAMPLE_RATE if mode == "match" else 2.0
    interval = max(1, int(round(fps / target_sample_rate))) if fps > 0 else max(1, int(round(1 / target_sample_rate)))
    actual_interval = interval / fps if fps > 0 else 1 / target_sample_rate
    max_samples = MATCH_MAX_SAMPLES if mode == "match" else 120
    frames = []
    sampled_video_frames = 0
    pose_detected_frames = 0
    frame_idx = 0
    target_jerseys = [x.strip() for x in (jersey_numbers or "10,74").replace("；", ",").split(",") if x.strip()]
    with mp_pose.Pose(static_image_mode=(mode == "match"), model_complexity=1,
                      enable_segmentation=False, min_detection_confidence=0.5,
                      min_tracking_confidence=0.5) as pose:
        while sampled_video_frames < max_samples:
            if mode == "match":
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ok, frame = cap.read()
                current_frame_idx = frame_idx
                frame_idx += interval
            else:
                ok, frame = cap.read()
                current_frame_idx = frame_idx
                frame_idx += 1
            if not ok:
                break
            if mode == "match" or current_frame_idx % interval == 0:
                sampled_video_frames += 1
                h, w = frame.shape[:2]
                if w > 960:
                    new_h = max(1, int(round(h * 960 / w)))
                    frame = cv2.resize(frame, (960, new_h), interpolation=cv2.INTER_AREA)
                metrics = analyze_frame(frame, pose)
                if metrics:
                    pose_detected_frames += 1
                    if mode == "match":
                        metrics["jersey_ocr_candidates"] = read_jersey_number(frame, metrics.get("landmarks", {}), target_jerseys)
                    frames.append({"time_seconds": round(current_frame_idx / fps, 2) if fps > 0 else current_frame_idx,
                                   **metrics})
                if progress_callback and duration > 0:
                    progress_callback(min(90, 15 + int(75 * min(1.0, (current_frame_idx / fps if fps > 0 else 0) / duration))))
    cap.release()
    if not frames:
        raise HTTPException(status_code=422, detail="人物の姿勢を検出できませんでした。人物全身が見える明るい動画で再試行してください。")
    knees = [x[k] for x in frames for k in ("left_knee_angle_deg", "right_knee_angle_deg") if x.get(k) is not None]
    trunks = [x["trunk_lean_image_angle_deg"] for x in frames if x.get("trunk_lean_image_angle_deg") is not None]
    hips = [x[k] for x in frames for k in ("left_hip_angle_deg", "right_hip_angle_deg") if x.get(k) is not None]
    # Estimate ankle/foot landmark movement after converting normalized x/y to pixel geometry.
    # Values are frame-widths per second, not real-world speed; camera motion and perspective affect them.
    for i, current in enumerate(frames):
        for side in ("left", "right"):
            key = side + "_foot_index"
            prev = frames[i - 1] if i > 0 else None
            a = current.get("landmarks", {}).get(key)
            b = prev.get("landmarks", {}).get(key) if prev else None
            dt = (current.get("time_seconds", 0) - prev.get("time_seconds", 0)) if prev else 0
            adjacent_sample = has_adjacent_sample_timing(
                current.get("time_seconds"), prev.get("time_seconds"), actual_interval
            ) if prev else False
            if a and b and adjacent_sample and a[2] >= 0.5 and b[2] >= 0.5:
                current[side + "_foot_image_motion_per_sec"] = image_motion_per_width_per_second(a, b, dt, frame.shape[1], frame.shape[0])
            else:
                current[side + "_foot_image_motion_per_sec"] = None
    kick_phase_candidates = build_kick_phase_candidates(frames, actual_interval, preferred_foot=preferred_foot) if mode == "form" else None
    summary = {
        "sampled_pose_frames": len(frames),
        "video_scan_quality": build_video_scan_quality(sampled_video_frames, pose_detected_frames),
        "duration_seconds": round(duration, 2),
        "average_left_right_knee_angle_deg": round(float(np.mean(knees)), 1) if knees else None,
        "average_trunk_lean_image_angle_deg": round(float(np.mean(trunks)), 1) if trunks else None,
        "average_left_right_hip_angle_deg": round(float(np.mean(hips)), 1) if hips else None,
        "sampling_interval_seconds": round(actual_interval, 3),
        "sampling_rate_fps": round(1 / actual_interval, 2) if actual_interval > 0 else None,
        "frames": frames,
    }
    if mode == "form":
        summary["capture_quality"] = build_form_capture_quality(frames)
        summary["kick_phase_candidates"] = kick_phase_candidates
    if mode == "match":
        jersey_counts = {}
        for frame_data in frames:
            for item in frame_data.get("jersey_ocr_candidates", []):
                number = item.get("number")
                if number:
                    jersey_counts[number] = jersey_counts.get(number, 0) + 1
        summary["jersey_ocr_summary"] = {
            "candidate_frame_counts": jersey_counts,
            "note": "姿勢検出できた1人分の胴体領域に対するOCR候補です。複数選手の検出・追跡や本人確認ではありません。"
        }
    if mode == "form":
        summary["measurement_provenance"] = {
            "source": "MediaPipe Pose landmark geometry",
            "visibility_threshold": 0.5,
            "quality_field": "frames[].metric_quality",
            "ai_measured": ["可視性条件を満たした膝・股関節角度", "画像上の体幹傾き", "画像座標上の足先移動量"],
            "manual_review_required": ["軸足とボールの距離", "インパクト時の接触位置・時刻", "キック速度", "狙ったコース", "フォームの良否"],
            "note": "可視性が不足する関節角度はnullとして扱い、平均値から除外します。"
        }
        tips = []
        if summary["average_left_right_knee_angle_deg"] is not None:
            tips.append("膝角度は映像上の推定値です。蹴る瞬間の軸足・膝の曲がりを、正面と横からの動画で比較してください。")
        if summary["average_left_right_hip_angle_deg"] is not None:
            tips.append("股関節角度（左右平均・画像上の推定）も算出しました。蹴る直前からインパクト後までの変化を確認してください。")
        tips.append("体幹の傾きは画像上の推定値です。カメラ位置・遠近・選手の向きで変わるため、数値だけで良し悪しを断定しません。")
        tips.append("足先の画像上の移動量も参考値として算出しますが、実速度ではありません。カメラ移動・遠近・遮蔽の影響を受けます。")
        tips.append("この解析では軸足とボールの距離、足とボールの接触位置、インパクト時刻、キック速度、狙ったコースは自動判定していません。")
        summary["feedback"] = tips
        summary["camera_angle_guidance"] = camera_angle_guidance(camera_angle)
        summary["camera_angle"] = camera_angle
    else:
        summary["feedback"] = [
            "この段階では動画全体を低頻度でスキャンし、画面内で検出できた人物の姿勢を記録します。",
            "背番号OCRは姿勢検出した1人分の胴体領域から10・74などの数字を読む試験機能です。読み取りミスや見逃しがあり、本人確認には使えません。",
            "複数選手の同時検出・追跡、陸玖本人の個体識別、プレー内容の自動判定、ハイライト編集は今後の開発段階です。",
            "姿勢検出フレームは陸玖本人と確認されたものではありません。"
        ]
        summary["scan_type"] = "full_video_coarse_pose_scan"
        summary["identity_confirmed"] = False
    return {"ok": True, "mode": mode, "engine": "MediaPipe Pose (open-source)", "summary": summary}

@app.get("/")
def root():
    return {"service": APP_NAME, "status": "ready", "docs": "/docs", "free_tier_note": "CPU/video limits apply"}

@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "pose_engine": "MediaPipe Pose"}

async def analyze_upload(file: UploadFile, mode: str, preferred_foot: str = "right"):
    if not file.filename:
        raise HTTPException(status_code=400, detail="動画ファイルがありません。")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}:
        suffix = ".mp4"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="ファイルが空です。")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"ファイルは{MAX_UPLOAD_MB}MB以内にしてください。")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            temp_path = tmp.name
        try:
            return process_video(temp_path, mode, preferred_foot=preferred_foot)
        except HTTPException as exc:
            # iPhone videos may be MOV/HEVC. OpenCV often cannot decode them
            # directly, so normalize to broadly supported H.264 MP4 with ffmpeg.
            if "動画を開けませんでした" not in str(exc.detail):
                raise
            converted_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as converted:
                    converted_path = converted.name
                command = [
                    "ffmpeg", "-y", "-i", temp_path,
                    "-map", "0:v:0", "-an",
                    "-vf", "scale='min(1280,iw)':-2",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    converted_path,
                ]
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                if result.returncode != 0:
                    raise HTTPException(
                        status_code=422,
                        detail="動画をMP4に変換できませんでした。iPhoneの写真アプリで再生できる動画を選び直してください。"
                    )
                return process_video(converted_path, mode, preferred_foot=preferred_foot)
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=408, detail="動画変換が時間内に完了しませんでした。")
            finally:
                if converted_path and os.path.exists(converted_path):
                    os.remove(converted_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/analyze/form")
async def analyze_form(file: UploadFile = File(...), kick_type: str = Form("シュート"), dominant_foot: str = Form("右足"), camera_angle: str = Form("未選択")):
    normalized_foot = "left" if dominant_foot in ("左足", "left") else "right"
    result = await analyze_upload(file, "form", preferred_foot=normalized_foot)
    result["kick_type"] = kick_type
    result["dominant_foot"] = dominant_foot
    result["camera_angle"] = camera_angle
    result["summary"]["camera_angle"] = camera_angle
    result["summary"]["camera_angle_guidance"] = camera_angle_guidance(camera_angle)
    return result

@app.post("/analyze/match")
async def analyze_match(file: UploadFile = File(...), jersey_numbers: str = Form("10,74")):
    result = await analyze_upload(file, "match")
    result["requested_jersey_numbers"] = jersey_numbers
    return result


def build_movement_candidates(summary, max_events=8):
    """Select conservative, temporally supported movement candidates from pose evidence."""
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

def extract_candidate_clips(video_path, job_id, candidates, duration, timing_metrics=None):
    clips = []
    per_clip_timings = []
    extraction_started = time.perf_counter()
    for event in candidates:
        clip_started = time.perf_counter()
        center = float(event['time_seconds'])
        start = max(0.0, center - 4.0)
        length = min(8.0, max(0.5, duration - start))
        if length < 0.5:
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
            clip_path = tmp.name
        command = ['ffmpeg', '-y', '-ss', str(start), '-i', video_path, '-t', str(length),
                   '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'ultrafast',
                   '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip_path]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
        clip_size = 0
        if proc.returncode == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            clip_size = os.path.getsize(clip_path)
            clips.append({'id': event['id'], 'time_seconds': event['time_seconds'],
                          'label': event['label'], 'reason': event['reason'], 'path': clip_path})
        else:
            if os.path.exists(clip_path):
                os.remove(clip_path)
        per_clip_timings.append({
            "candidate_id": str(event.get("id", "")),
            "elapsed_seconds": round(time.perf_counter() - clip_started, 4),
            "output_size_bytes": clip_size,
            "succeeded": clip_size > 0,
        })
    if timing_metrics is not None:
        timing_metrics["clip_extraction_seconds"] = round(time.perf_counter() - extraction_started, 4)
        timing_metrics["clip_extraction_per_clip"] = per_clip_timings
    return clips


def analyze_candidate_clip_dense(clip_path, jersey_numbers=None, sample_rate=1.5, max_samples=16):
    """Re-scan a short movement candidate at a denser rate and summarize provisional tracks."""
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise RuntimeError("候補動画を開けませんでした。")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if fps > 0 else 0
    interval = max(1, int(round(fps / sample_rate))) if fps > 0 else 1
    actual_rate = fps / interval if fps > 0 else sample_rate
    targets = [x.strip() for x in (jersey_numbers or "10,74").replace("；", ",").split(",") if x.strip()]
    frames, jersey_counts, people_counts = [], {}, []
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=POSE_LANDMARKER_MODEL),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=8,
        min_pose_detection_confidence=0.35,
        min_pose_presence_confidence=0.35,
        min_tracking_confidence=0.35,
    )
    try:
        with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
            sample_index = 0
            frame_index = 0
            while sample_index < max_samples and (duration <= 0 or frame_index / max(fps, 1) <= duration):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, max(1, int(round(h * 960 / w)))), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(sample_index * 1000 / max(actual_rate, 0.1))
                detected = landmarker.detect_for_video(mp_image, timestamp_ms)
                people = []
                for person_index, pose_lm in enumerate(detected.pose_landmarks or []):
                    metrics = analyze_task_pose(pose_lm, frame.shape[1], frame.shape[0])
                    ocr = read_jersey_number(frame, metrics["landmarks"], targets)
                    for item in ocr:
                        jersey_counts[item["number"]] = jersey_counts.get(item["number"], 0) + 1
                    people.append({
                        "person_index": person_index,
                        "visible_landmarks": metrics["visible_landmarks"],
                        "bbox": metrics["bbox"],
                        "jersey_ocr_candidates": ocr,
                    })
                frames.append({
                    "time_seconds": round(frame_index / fps, 2) if fps > 0 else round(sample_index / max(actual_rate, 0.1), 2),
                    "detected_people": people,
                    "detected_people_in_frame": len(people),
                })
                people_counts.append(len(people))
                frame_index += interval
                sample_index += 1
    finally:
        cap.release()
    track_summary = associate_person_tracks(frames, max_gap_seconds=max(1.5, 2.2 / max(actual_rate, 0.1)))
    return {
        "sampled_frames": len(frames),
        "sampling_rate_fps": round(actual_rate, 2),
        "duration_seconds": round(duration, 2),
        "max_people_in_one_frame": max(people_counts) if people_counts else 0,
        "jersey_candidate_detection_counts": jersey_counts,
        "track_summary": track_summary,
        "note": "候補動画を約1.5fpsで再解析した暫定結果です。トラックID・背番号候補は本人確認ではなく、選手の交差や遮蔽で入れ替わる可能性があります。"
    }




def build_candidate_frame_time_index(summary):
    """Build a reusable time index; return None for non-monotonic input to preserve fallback semantics."""
    frames = summary.get("frames", []) if isinstance(summary, dict) else []
    indexed_frames = []
    previous_time = None
    for source_frame in frames if isinstance(frames, list) else []:
        if not isinstance(source_frame, dict):
            continue
        try:
            timestamp = float(source_frame.get("time_seconds"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(timestamp):
            continue
        if previous_time is not None and timestamp < previous_time:
            return None
        indexed_frames.append((timestamp, source_frame))
        previous_time = timestamp
    return {
        "timestamps": [item[0] for item in indexed_frames],
        "frames": [item[1] for item in indexed_frames],
    }


def summarize_candidate_from_full_scan(summary, center_time, clip_duration=8.0,
                                       frame_index=None, timing_metrics=None):
    """Reuse indexed full-match pose detections without changing the selected time window."""
    if not isinstance(summary, dict):
        return {"sampled_frames": 0, "track_summary": {"provisional_track_count": 0, "tracks": []}}
    try:
        center = float(center_time)
        video_duration = float(summary.get("duration_seconds") or 0)
        requested_length = max(0.5, float(clip_duration))
    except (TypeError, ValueError, OverflowError):
        return {"sampled_frames": 0, "track_summary": {"provisional_track_count": 0, "tracks": []}}
    if not np.isfinite(center) or not np.isfinite(video_duration) or not np.isfinite(requested_length):
        return {"sampled_frames": 0, "track_summary": {"provisional_track_count": 0, "tracks": []}}
    start = max(0.0, center - 4.0)
    length = min(requested_length, max(0.5, video_duration - start)) if video_duration > 0 else requested_length
    end = start + length
    try:
        interval = float(summary.get("sampling_interval_seconds") or 0.5)
    except (TypeError, ValueError, OverflowError):
        interval = 0.5
    if not np.isfinite(interval) or interval <= 0:
        interval = 0.5

    candidate_frames = []
    jersey_counts = {}
    people_counts = []
    filter_started = time.perf_counter() if timing_metrics is not None else None
    all_frames = summary.get("frames", [])
    if (isinstance(frame_index, dict)
            and isinstance(frame_index.get("timestamps"), list)
            and isinstance(frame_index.get("frames"), list)
            and len(frame_index["timestamps"]) == len(frame_index["frames"])):
        timestamps = frame_index["timestamps"]
        left = bisect.bisect_left(timestamps, start - 1e-6)
        right = bisect.bisect_right(timestamps, end + 1e-6)
        source_frames = frame_index["frames"][left:right]
    else:
        source_frames = all_frames
    for source_frame in source_frames:
        if not isinstance(source_frame, dict):
            continue
        try:
            timestamp = float(source_frame.get("time_seconds"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(timestamp) or timestamp < start - 1e-6 or timestamp > end + 1e-6:
            continue
        source_people = source_frame.get("detected_people")
        if not isinstance(source_people, list):
            source_people = []
            if source_frame.get("bbox"):
                source_people.append({
                    "person_index": source_frame.get("person_index", 0),
                    "bbox": source_frame.get("bbox"),
                    "jersey_ocr_candidates": source_frame.get("jersey_ocr_candidates", []),
                })
        people = [dict(person) for person in source_people
                  if isinstance(person, dict) and isinstance(person.get("bbox"), (list, tuple))
                  and len(person.get("bbox")) == 4]
        for person in people:
            for item in person.get("jersey_ocr_candidates", []):
                if isinstance(item, dict) and item.get("number") is not None:
                    number = str(item["number"])
                    jersey_counts[number] = jersey_counts.get(number, 0) + 1
        if people:
            candidate_frames.append({
                "time_seconds": round(timestamp, 2),
                "detected_people": people,
                "detected_people_in_frame": len(people),
            })
            people_counts.append(len(people))

    frame_filter_seconds = time.perf_counter() - filter_started if filter_started is not None else 0.0
    association_started = time.perf_counter() if timing_metrics is not None else None
    actual_rate = 1.0 / interval
    tracks = associate_person_tracks(
        candidate_frames,
        max_gap_seconds=max(1.5, interval * 2.2),
    )
    association_seconds = time.perf_counter() - association_started if association_started is not None else 0.0
    if timing_metrics is not None:
        timing_metrics["frame_filter_seconds"] = round(frame_filter_seconds, 4)
        timing_metrics["track_association_seconds"] = round(association_seconds, 4)
        timing_metrics["candidate_frames_selected"] = len(candidate_frames)
    return {
        "sampled_frames": len(candidate_frames),
        "sampling_rate_fps": round(actual_rate, 2),
        "duration_seconds": round(length, 2),
        "max_people_in_one_frame": max(people_counts) if people_counts else 0,
        "jersey_candidate_detection_counts": jersey_counts,
        "track_summary": tracks,
        "reused_full_scan": True,
        "note": "全編スキャンで取得済みの約2fps姿勢データを再利用しています。候補場面のためのMediaPipe再推定は行っていません。トラックID・背番号候補は本人確認ではありません。",
    }


def _set_match_job(job_id: str, **updates):
    job = match_jobs.get(job_id)
    if job is not None:
        job.update(updates)
        persist_match_job_state(job_id, job)


def can_decode_video_first_frame(path: str) -> bool:
    """Check whether OpenCV can decode the source before paying for a full FFmpeg re-encode."""
    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            return False
        ok, frame = capture.read()
        if not ok or frame is None:
            return False
        height, width = frame.shape[:2]
        # Keep the existing 960px normalization for larger inputs. Decoding
        # full-resolution phone footage repeatedly can cost more than the
        # one-time conversion we are trying to avoid.
        return width <= 960
    except Exception:
        return False
    finally:
        capture.release()


def run_match_job(job_id: str, source_path: str, jersey_numbers: str):
    converted_path = None
    analysis_path = source_path
    job_started_at = time.monotonic()
    conversion_seconds = 0.0
    pose_scan_seconds = 0.0
    candidate_seconds = 0.0
    conversion_skipped = False
    try:
        source_size = os.path.getsize(source_path)
        capacity = match_upload_disk_capacity(source_size + MATCH_UPLOAD_DISK_RESERVE_BYTES)
        if not capacity["ok"]:
            raise RuntimeError(
                "解析用の一時ファイルを作る空き容量がありません。"
                f" 空き容量: {capacity['free_bytes']} bytes / "
                f"必要目安: {capacity['required_bytes']} bytes"
            )
        if can_decode_video_first_frame(source_path):
            conversion_skipped = True
            _set_match_job(job_id, status="processing", progress=15, stage="元動画を直接スキャン中（変換を省略）")
        else:
            _set_match_job(job_id, status="processing", progress=5, stage="動画を解析用MP4に変換中")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as converted:
                converted_path = converted.name
            command = [
                "ffmpeg", "-y", "-i", source_path, "-map", "0:v:0", "-an",
                "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264",
                "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", converted_path,
            ]
            conversion_started_at = time.monotonic()
            converted_result = subprocess.run(command, capture_output=True, text=True, timeout=900)
            conversion_seconds = time.monotonic() - conversion_started_at
            if converted_result.returncode != 0:
                raise RuntimeError("動画を解析用MP4に変換できませんでした。")
            analysis_path = converted_path
        _set_match_job(job_id, progress=15, stage="動画全体をスキャン中")
        def progress(value):
            _set_match_job(job_id, progress=value, stage="動画全体をスキャン中")
        pose_scan_started_at = time.monotonic()
        result = process_video(analysis_path, "match", progress_callback=progress, jersey_numbers=jersey_numbers)
        pose_scan_seconds = time.monotonic() - pose_scan_started_at
        summary = result.get("summary", {})
        candidate_pipeline_started_at = time.perf_counter()
        candidate_selection_started_at = time.perf_counter()
        candidates = build_movement_candidates(summary)
        candidate_selection_seconds = time.perf_counter() - candidate_selection_started_at
        frame_index_started_at = time.perf_counter()
        candidate_frame_index = build_candidate_frame_time_index(summary)
        candidate_frame_index_seconds = time.perf_counter() - frame_index_started_at
        _set_match_job(job_id, progress=92, stage="動きの候補場面を短い動画に切り出し中")
        clip_timing_metrics = {}
        clips = extract_candidate_clips(
            analysis_path, job_id, candidates,
            float(summary.get("duration_seconds", 0)),
            timing_metrics=clip_timing_metrics,
        )
        clip_extraction_seconds = clip_timing_metrics.get("clip_extraction_seconds", 0.0)
        dense_analysis_seconds = 0.0
        candidate_summary_timings = []
        clip_by_id = {str(clip["id"]): clip for clip in clips}
        for event in candidates:
            matching_clip = clip_by_id.get(str(event["id"]))
            event["clip_available"] = matching_clip is not None
            if matching_clip:
                event["clip_url"] = f"/analyze/jobs/{job_id}/clips/{event['id']}"
                summary_started_at = time.perf_counter()
                summary_timing = {}
                try:
                    event["dense_analysis"] = summarize_candidate_from_full_scan(
                        summary, event["time_seconds"], clip_duration=8.0,
                        frame_index=candidate_frame_index, timing_metrics=summary_timing,
                    )
                except Exception as clip_exc:
                    event["dense_analysis"] = {"error": str(clip_exc), "note": "全編スキャンデータから候補トラックを整理できませんでした。"}
                finally:
                    elapsed = time.perf_counter() - summary_started_at
                    matching_clip["dense_analysis_seconds"] = round(elapsed, 4)
                    dense_analysis_seconds += elapsed
                    candidate_summary_timings.append({
                        "candidate_id": str(event["id"]),
                        "total_seconds": round(elapsed, 4),
                        **summary_timing,
                    })
        candidate_seconds = time.perf_counter() - candidate_pipeline_started_at
        total_processing_seconds = time.monotonic() - job_started_at
        sampled_frames = int(summary.get("video_scan_quality", {}).get("sampled_video_frames") or 0)
        summary["performance_metrics"] = {
            "conversion_seconds": round(conversion_seconds, 2),
            "pose_scan_seconds": round(pose_scan_seconds, 2),
            "candidate_and_clip_seconds": round(candidate_seconds, 2),
            "candidate_selection_seconds": round(candidate_selection_seconds, 4),
            "candidate_frame_index_seconds": round(candidate_frame_index_seconds, 4),
            "clip_extraction_seconds": round(clip_extraction_seconds, 4),
            "clip_extraction_per_clip": clip_timing_metrics.get("clip_extraction_per_clip", []),
            "candidate_track_summary_seconds": round(dense_analysis_seconds, 4),
            "candidate_track_summary_per_candidate": candidate_summary_timings,
            "candidate_frame_filter_seconds": round(sum(x.get("frame_filter_seconds", 0) for x in candidate_summary_timings), 4),
            "candidate_track_association_seconds": round(sum(x.get("track_association_seconds", 0) for x in candidate_summary_timings), 4),
            "dense_candidate_analysis_seconds": round(dense_analysis_seconds, 4),
            "total_processing_seconds": round(total_processing_seconds, 2),
            "pose_samples_per_second": round(sampled_frames / pose_scan_seconds, 2) if pose_scan_seconds > 0 else None,
            "sampled_frames": sampled_frames,
            "pose_scan_breakdown": summary.get("scan_timing", {}),
            "pose_inference_sample_count": summary.get("scan_timing", {}).get("pose_inference_sample_count"),
            "pose_inference_p50_seconds": summary.get("scan_timing", {}).get("pose_inference_p50_seconds"),
            "pose_inference_p95_seconds": summary.get("scan_timing", {}).get("pose_inference_p95_seconds"),
            "pose_inference_max_seconds": summary.get("scan_timing", {}).get("pose_inference_max_seconds"),
            "candidate_count": len(candidates),
            "clip_count": len(clips),
            "conversion_skipped": conversion_skipped,
            "input_decode_preflight": "first_frame_decodable" if conversion_skipped else "fallback_conversion",
            "note": "入力動画の直接デコードで再エンコードを省略し、候補場面の追跡整理には全編スキャン済みの姿勢データを再利用します。"
        }
        summary["candidate_events"] = candidates
        summary["candidate_event_count"] = len(candidates)
        summary["candidate_event_note"] = "足先の画像上の動きから抽出した確認候補です。候補動画は約1.5fpsで追加解析しますが、サッカーのプレーや陸玖本人の動きと確認されたものではありません。"
        result["requested_jersey_numbers"] = jersey_numbers
        result["job_id"] = job_id
        _set_match_job(job_id, status="completed", progress=100, stage="解析完了", result=result, clips=clips)
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _set_match_job(job_id, status="failed", progress=100, stage="解析に失敗", error=detail)
    finally:
        for path in (source_path, converted_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if job_id in match_jobs:
            persist_match_job_state(job_id, match_jobs[job_id])


def resume_interrupted_match_jobs():
    """Resume queued jobs only when their original temporary video still exists."""
    for job_id, job in list(match_jobs.items()):
        if job.get("status") != "queued":
            continue
        source_path = job.get("source_path")
        if not source_path or not os.path.isfile(source_path):
            job.update(
                status="failed", progress=100, stage="解析を再開できません",
                error="サーバー再起動後に元動画の一時ファイルが見つかりません。動画を再送信してください。",
            )
            persist_match_job_state(job_id, job)
            continue
        worker = threading.Thread(
            target=run_match_job,
            args=(job_id, source_path, str(job.get("jersey_numbers") or "10,74")),
            daemon=True,
        )
        worker.start()


@app.on_event("startup")
def resume_saved_match_jobs_on_startup():
    resume_interrupted_match_jobs()


def append_match_upload_chunk(upload_state, chunk_index, data):
    """Append one ordered, retry-safe chunk to a temporary match-video upload."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("動画の分割データが空です。")
    index = int(chunk_index)
    digest = hashlib.sha256(data).hexdigest()
    received = upload_state.setdefault("chunk_hashes", {})
    next_index = int(upload_state.get("next_chunk", 0))
    if index < next_index:
        if received.get(index) == digest:
            return False
        raise ValueError("同じ分割番号に異なる動画データが届きました。")
    if index != next_index:
        raise ValueError("動画データの順番が一致しません。")
    chunk_size = int(upload_state["chunk_size"])
    total_size = int(upload_state["total_size"])
    written = int(upload_state.get("received_bytes", 0))
    expected = min(chunk_size, total_size - written)
    if expected <= 0 or len(data) != expected:
        raise ValueError("動画データのサイズが一致しません。")
    with open(upload_state["path"], "ab") as target:
        target.write(data)
    received[index] = digest
    upload_state["next_chunk"] = next_index + 1
    upload_state["received_bytes"] = written + len(data)
    return True


@app.post("/analyze/match/uploads", status_code=201)
async def create_match_upload(payload: dict = Body(...)):
    filename = Path(str(payload.get("filename") or "match-video.mp4")).name
    total_size = payload.get("size_bytes")
    duration = payload.get("duration_seconds")
    if isinstance(total_size, bool) or not isinstance(total_size, int) or total_size <= 0:
        raise HTTPException(status_code=400, detail="動画ファイルのサイズを確認できません。")
    if total_size > MAX_MATCH_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"試合動画は{MAX_MATCH_UPLOAD_MB}MB以内にしてください。")
    # Keep room for the uploaded source, a similarly-sized FFmpeg output, and a safety reserve.
    required_disk_bytes = (total_size * 2) + MATCH_UPLOAD_DISK_RESERVE_BYTES
    capacity = match_upload_disk_capacity(required_disk_bytes)
    if not capacity["ok"]:
        raise HTTPException(
            status_code=507,
            detail={
                "code": "insufficient_server_disk_space",
                "message": "サーバーの空き容量が不足しているため、動画のアップロードを開始できません。",
                "free_bytes": capacity["free_bytes"],
                "required_bytes": capacity["required_bytes"],
                "reserve_mb": MATCH_UPLOAD_DISK_RESERVE_BYTES // (1024 * 1024),
            },
        )
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError, OverflowError):
        duration_value = None
    if duration_value is not None and duration_value > MAX_MATCH_SECONDS:
        raise HTTPException(status_code=413, detail=f"試合動画は{MAX_MATCH_SECONDS // 60}分以内にしてください。")
    upload_id = uuid.uuid4().hex
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix or ".mp4") as tmp:
        temp_path = tmp.name
    chunks = (total_size + MATCH_UPLOAD_CHUNK_BYTES - 1) // MATCH_UPLOAD_CHUNK_BYTES
    match_uploads[upload_id] = {
        "path": temp_path, "filename": filename, "total_size": total_size,
        "duration_seconds": duration_value, "chunk_size": MATCH_UPLOAD_CHUNK_BYTES,
        "total_chunks": chunks, "next_chunk": 0, "received_bytes": 0,
        "chunk_hashes": {}, "jersey_numbers": str(payload.get("jersey_numbers") or "10,74"),
    }
    persist_match_upload_state(upload_id, match_uploads[upload_id])
    return {"ok": True, "upload_id": upload_id, "chunk_size": MATCH_UPLOAD_CHUNK_BYTES,
            "total_chunks": chunks, "max_upload_mb": MAX_MATCH_UPLOAD_MB,
            "max_duration_seconds": MAX_MATCH_SECONDS}


@app.get("/analyze/match/uploads/{upload_id}")
def get_match_upload_status(upload_id: str):
    upload_state = match_uploads.get(upload_id)
    if upload_state is None:
        raise HTTPException(status_code=404, detail="動画アップロードが見つかりません。最初から再試行してください。")
    return {
        "ok": True, "upload_id": upload_id,
        "next_chunk": upload_state["next_chunk"],
        "total_chunks": upload_state["total_chunks"],
        "received_bytes": upload_state["received_bytes"],
        "total_bytes": upload_state["total_size"],
        "complete": upload_state["received_bytes"] == upload_state["total_size"],
    }


@app.put("/analyze/match/uploads/{upload_id}/{chunk_index}")
async def upload_match_chunk(upload_id: str, chunk_index: int, file: UploadFile = File(...)):
    upload_state = match_uploads.get(upload_id)
    if upload_state is None:
        raise HTTPException(status_code=404, detail="動画アップロードが見つかりません。最初から再試行してください。")
    if chunk_index < 0 or chunk_index >= upload_state["total_chunks"]:
        raise HTTPException(status_code=400, detail="動画データの分割番号が不正です。")
    data = await file.read(MATCH_UPLOAD_CHUNK_BYTES + 1)
    if len(data) > MATCH_UPLOAD_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="分割データが上限を超えています。")
    try:
        if chunk_index == int(upload_state.get("next_chunk", 0)):
            remaining_after_chunk = max(
                0, int(upload_state["total_size"]) - int(upload_state["received_bytes"]) - len(data)
            )
            processing_headroom = int(upload_state["total_size"]) + MATCH_UPLOAD_DISK_RESERVE_BYTES
            capacity = match_upload_disk_capacity(remaining_after_chunk + processing_headroom)
            if not capacity["ok"]:
                raise HTTPException(
                    status_code=507,
                    detail={
                        "code": "insufficient_server_disk_space",
                        "message": "サーバーの空き容量が不足したため、次の分割データを保存できません。容量を確保してから再試行してください。",
                        "free_bytes": capacity["free_bytes"],
                        "required_bytes": capacity["required_bytes"],
                    },
                )
        added = append_match_upload_chunk(upload_state, chunk_index, data)
        if added:
            persist_match_upload_state(upload_id, upload_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=507, detail="アップロード状態を保存できません。空き容量を確認してください。")
    return {"ok": True, "chunk_index": chunk_index, "received_bytes": upload_state["received_bytes"],
            "total_bytes": upload_state["total_size"], "duplicate_retry": not added}


@app.post("/analyze/match/uploads/{upload_id}/complete", status_code=202)
async def complete_match_upload(upload_id: str, background_tasks: BackgroundTasks):
    # A client may lose the HTTP response after the job was queued. Return the
    # original job on retry instead of creating duplicate analysis work.
    completed_job_id = completed_match_uploads.get(upload_id)
    if completed_job_id:
        job = match_jobs.get(completed_job_id)
        if job:
            return {"ok": True, "job_id": completed_job_id, "status": job.get("status", "queued"),
                    "status_url": f"/analyze/jobs/{completed_job_id}"}
        completed_match_uploads.pop(upload_id, None)
    upload_state = match_uploads.get(upload_id)
    if upload_state is None:
        raise HTTPException(status_code=404, detail="動画アップロードが見つかりません。最初から再試行してください。")
    if (upload_state["next_chunk"] != upload_state["total_chunks"]
            or upload_state["received_bytes"] != upload_state["total_size"]):
        raise HTTPException(status_code=409, detail="動画の受信が完了していません。未送信の分割データがあります。")
    job_id = uuid.uuid4().hex
    temp_path = upload_state["path"]
    jersey_numbers = upload_state["jersey_numbers"]
    match_jobs[job_id] = {
        "job_id": job_id, "status": "queued", "progress": 0,
        "stage": "解析待ち", "filename": upload_state["filename"],
        "size_bytes": upload_state["total_size"], "result": None, "error": None,
        "source_path": temp_path, "upload_id": upload_id, "jersey_numbers": jersey_numbers,
    }
    persist_match_job_state(job_id, match_jobs[job_id])
    del match_uploads[upload_id]
    match_upload_manifest_path(upload_id).unlink(missing_ok=True)
    completed_match_uploads[upload_id] = job_id
    # Keep this in-memory retry cache bounded for the free single-instance service.
    while len(completed_match_uploads) > 256:
        completed_match_uploads.pop(next(iter(completed_match_uploads)))
    background_tasks.add_task(run_match_job, job_id, temp_path, jersey_numbers)
    return {"ok": True, "job_id": job_id, "status": "queued",
            "status_url": f"/analyze/jobs/{job_id}"}


@app.delete("/analyze/match/uploads/{upload_id}")
def cancel_match_upload(upload_id: str):
    upload_state = match_uploads.pop(upload_id, None)
    match_upload_manifest_path(upload_id).unlink(missing_ok=True)
    if upload_state is None:
        return {"ok": True, "already_closed": True}
    try:
        if os.path.exists(upload_state["path"]):
            os.remove(upload_state["path"])
    except OSError:
        pass
    return {"ok": True, "cancelled": True}

@app.post("/analyze/match/jobs", status_code=202)
async def create_match_job(background_tasks: BackgroundTasks, file: UploadFile = File(...),
                           jersey_numbers: str = Form("10,74")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="動画ファイルがありません。")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}:
        suffix = ".mp4"
    job_id = __import__("uuid").uuid4().hex
    temp_path = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_MATCH_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"試合動画は{MAX_MATCH_UPLOAD_MB}MB以内にしてください。")
                tmp.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="ファイルが空です。")
        match_jobs[job_id] = {
            "job_id": job_id, "status": "queued", "progress": 0,
            "stage": "解析待ち", "filename": file.filename,
            "size_bytes": size, "result": None, "error": None,
            "source_path": temp_path, "jersey_numbers": jersey_numbers,
        }
        persist_match_job_state(job_id, match_jobs[job_id])
        background_tasks.add_task(run_match_job, job_id, temp_path, jersey_numbers)
        return {"ok": True, "job_id": job_id, "status": "queued",
                "status_url": f"/analyze/jobs/{job_id}"}
    except Exception:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise


@app.get("/analyze/jobs/{job_id}")
def get_match_job(job_id: str):
    job = match_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="解析ジョブが見つかりません。サーバー再起動後は再送信が必要です。")
    payload = {key: value for key, value in job.items() if key not in {"result", "clips"}}
    if job.get("status") == "completed":
        payload["result"] = job["result"]
        payload["clips"] = [{key: value for key, value in clip.items() if key != "path"} for clip in job.get("clips", [])]
    return payload

@app.post("/analyze/jobs/{job_id}/highlights")
def create_match_highlight(job_id: str, clip_ids: str = Form(...)):
    job = match_jobs.get(job_id)
    if job is None or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="完了した試合解析ジョブが見つかりません。")
    requested = [x.strip() for x in clip_ids.split(",") if x.strip()]
    if not requested or len(requested) > 8 or len(set(requested)) != len(requested):
        raise HTTPException(status_code=400, detail="ハイライトに含める場面は1〜8件選んでください。")
    clip_map = {str(x.get("id")): x for x in job.get("clips", [])}
    selected = [clip_map.get(x) for x in requested]
    if any(x is None or not os.path.isfile(x.get("path", "")) for x in selected):
        raise HTTPException(status_code=404, detail="選択した候補動画が見つかりません。試合動画を再解析してください。")
    list_path = None
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as listing:
            list_path = listing.name
            for clip in selected:
                listing.write("file '" + clip["path"] + "'\n")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as output:
            output_path = output.name
        command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                   "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("ハイライト動画を作成できませんでした。")
        old_path = job.get("highlight_path")
        if old_path and os.path.exists(old_path):
            os.remove(old_path)
        job["highlight_path"] = output_path
        job["highlight_clip_ids"] = requested
        return {"ok": True, "clip_count": len(selected),
                "url": f"/analyze/jobs/{job_id}/highlights"}
    except Exception as exc:
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if list_path and os.path.exists(list_path):
            os.remove(list_path)


@app.post("/analyze/highlights/collection")
def create_cross_match_highlight(payload: dict = Body(...)):
    requested = payload.get("clips", [])
    if not isinstance(requested, list) or not requested or len(requested) > 12:
        raise HTTPException(status_code=400, detail="ベストプレー集は1〜12場面を選んでください。")
    selected = []
    seen = set()
    for item in requested:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="場面情報が正しくありません。")
        job_id = str(item.get("job_id", "")).strip()
        clip_id = str(item.get("clip_id", "")).strip()
        key = (job_id, clip_id)
        if not job_id or not clip_id or key in seen:
            raise HTTPException(status_code=400, detail="場面情報が重複または不足しています。")
        seen.add(key)
        job = match_jobs.get(job_id)
        if job is None or job.get("status") != "completed":
            raise HTTPException(status_code=404, detail="過去の解析ジョブが見つかりません。サーバー再起動後は該当試合を再解析してください。")
        clip = next((x for x in job.get("clips", []) if str(x.get("id")) == clip_id), None)
        if clip is None or not os.path.isfile(clip.get("path", "")):
            raise HTTPException(status_code=404, detail="切り抜き動画が残っていません。該当試合を再解析してください。")
        selected.append(clip)
    list_path = None
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as listing:
            list_path = listing.name
            for clip in selected:
                safe_path = clip["path"].replace("'", "'\\''")
                listing.write("file '" + safe_path + "'\n")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as output:
            output_path = output.name
        command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                   "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=360)
        if proc.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("複数試合のベストプレー動画を作成できませんでした。")
        collection_id = uuid.uuid4().hex
        highlight_collections[collection_id] = {"path": output_path, "clip_count": len(selected)}
        return {"ok": True, "clip_count": len(selected), "url": f"/analyze/highlights/collection/{collection_id}"}
    except Exception as exc:
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if list_path and os.path.exists(list_path):
            os.remove(list_path)


@app.get("/analyze/highlights/collection/{collection_id}")
def get_cross_match_highlight(collection_id: str):
    collection = highlight_collections.get(collection_id)
    path = collection.get("path") if collection else None
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="ベストプレー集がありません。サーバー再起動後は再作成してください。")
    return FileResponse(path, media_type="video/mp4", filename="riku-best-plays.mp4")


@app.get("/analyze/jobs/{job_id}/highlights")
def get_match_highlight(job_id: str):
    job = match_jobs.get(job_id)
    path = job.get("highlight_path") if job else None
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="ハイライト動画がありません。先に作成してください。")
    return FileResponse(path, media_type="video/mp4", filename="riku-highlight.mp4")


@app.get("/analyze/jobs/{job_id}/clips/{clip_id}")
def get_match_candidate_clip(job_id: str, clip_id: str):
    job = match_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="解析ジョブが見つかりません。")
    clip = next((x for x in job.get("clips", []) if x.get("id") == clip_id), None)
    if clip is None or not os.path.exists(clip.get("path", "")):
        raise HTTPException(status_code=404, detail="候補動画が見つかりません。サーバー再起動後は再解析が必要です。")
    return FileResponse(clip["path"], media_type="video/mp4", filename=f"movement-candidate-{clip_id}.mp4")
