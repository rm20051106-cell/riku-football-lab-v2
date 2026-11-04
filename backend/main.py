import os
import re
import subprocess
import tempfile
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
MATCH_SAMPLE_RATE = float(os.getenv("MATCH_SAMPLE_RATE", "0.25"))
MATCH_MAX_SAMPLES = int(os.getenv("MATCH_MAX_SAMPLES", "360"))
POSE_LANDMARKER_MODEL = os.getenv("POSE_LANDMARKER_MODEL", "/app/models/pose_landmarker_lite.task")
match_jobs = {}
highlight_collections = {}

app = FastAPI(title=APP_NAME, version="0.1.0")
# Public demo configuration. Restrict CORS to the GitHub Pages URL after deployment.
allowed = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
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
    return {
        "visible_landmarks": visible,
        "measurement_source": "MediaPipe Pose landmark geometry",
        "metric_quality": metric_quality,
        "left_knee_angle_deg": left_knee,
        "right_knee_angle_deg": right_knee,
        "left_hip_angle_deg": left_hip,
        "right_hip_angle_deg": right_hip,
        "trunk_lean_image_angle_deg": trunk_angle,
        "landmarks": landmarks,
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
    def p(name):
        item = lm[mp_pose.PoseLandmark[name].value]
        visibility = float(getattr(item, "visibility", 1.0))
        return [float(item.x), float(item.y), visibility]
    visible = sum(1 for item in lm if float(getattr(item, "visibility", 1.0)) >= 0.5)
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
    target_rate = max(0.1, MATCH_SAMPLE_RATE)
    interval = max(1, int(round(fps / target_rate))) if fps > 0 else max(1, int(round(1 / target_rate)))
    actual_interval = interval / fps if fps > 0 else 1 / target_rate
    targets = [x.strip() for x in (jersey_numbers or "10,74").replace("；", ",").split(",") if x.strip()]
    frames, people_per_frame, jersey_counts = [], [], {}
    frame_idx, sample_index = 0, 0
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
            while sample_index < MATCH_MAX_SAMPLES:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ok, frame = cap.read()
                if not ok:
                    break
                current_frame_idx = frame_idx
                frame_idx += interval
                sample_index += 1
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, max(1, int(round(h * 960 / w)))), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int((current_frame_idx / fps if fps > 0 else sample_index * actual_interval) * 1000)
                detected = landmarker.detect_for_video(mp_image, timestamp_ms)
                people = []
                person_metrics = []
                time_seconds = round(current_frame_idx / fps, 2) if fps > 0 else round(sample_index * actual_interval, 2)
                detected_count = len(detected.pose_landmarks or [])
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
                if person_metrics:
                    primary = max(person_metrics, key=lambda x: x["visible_landmarks"])
                    primary["detected_people"] = people
                    frames.append(primary)
                if progress_callback and duration > 0:
                    progress_callback(min(90, 15 + int(75 * min(1.0, (current_frame_idx / fps if fps > 0 else 0) / duration))))
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
            if unique_person and a and b and dt > 0 and a[2] >= 0.5 and b[2] >= 0.5:
                current[side + "_foot_image_motion_per_sec"] = round(float(np.linalg.norm(np.array(a[:2]) - np.array(b[:2])) / dt), 4)
            else:
                current[side + "_foot_image_motion_per_sec"] = None
    track_summary = associate_person_tracks(frames, max_gap_seconds=max(9.0, actual_interval * 2.1))
    knees = [x[k] for x in frames for k in ("left_knee_angle_deg", "right_knee_angle_deg") if x.get(k) is not None]
    hips = [x[k] for x in frames for k in ("left_hip_angle_deg", "right_hip_angle_deg") if x.get(k) is not None]
    trunks = [x["trunk_lean_image_angle_deg"] for x in frames if x.get("trunk_lean_image_angle_deg") is not None]
    summary = {
        "sampled_pose_frames": len(frames),
        "duration_seconds": round(duration, 2),
        "average_left_right_knee_angle_deg": round(float(np.mean(knees)), 1) if knees else None,
        "average_trunk_lean_image_angle_deg": round(float(np.mean(trunks)), 1) if trunks else None,
        "average_left_right_hip_angle_deg": round(float(np.mean(hips)), 1) if hips else None,
        "sampling_interval_seconds": round(actual_interval, 3),
        "sampling_rate_fps": round(1 / actual_interval, 2) if actual_interval > 0 else None,
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


def build_kick_phase_candidates(frames, sampling_interval_seconds):
    """Return conservative image-motion time candidates, never definitive kick phases."""
    interval = float(sampling_interval_seconds or 0)
    result = {
        "sampling_interval_seconds": round(interval, 3),
        "sampling_rate_fps": round(1 / interval, 2) if interval > 0 else None,
        "method": "foot_index landmark image-coordinate motion",
        "limitations": [
            "画像上の足先移動候補であり、実空間速度・ボール接触・キック成功を示しません。",
            "助走・軸足接地・インパクトは骨格点だけでは確定できず、目視確認が必要です。",
            "カメラ移動・遠近・足先の遮蔽・別人物への検出切替で候補時刻がずれる場合があります。",
        ],
        "feet": {},
    }
    for side in ("left", "right"):
        valid = []
        for index, frame in enumerate(frames):
            speed = frame.get(side + "_foot_image_motion_per_sec")
            timestamp = frame.get("time_seconds")
            if isinstance(speed, (int, float)) and np.isfinite(speed) and isinstance(timestamp, (int, float)):
                valid.append({"frame_index": index, "time_seconds": round(float(timestamp), 3),
                              "image_motion_per_sec": round(float(speed), 5)})
        foot_result = {"sample_count": len(valid), "peak_candidate": None,
                       "post_peak_candidate": None, "opposite_foot_relative_stability": None,
                       "status": "insufficient_sampling"}
        if interval <= 0.75 and len(valid) >= 4:
            peak = max(valid, key=lambda item: item["image_motion_per_sec"])
            peak_speed = peak["image_motion_per_sec"]
            if peak_speed > 0:
                foot_result["peak_candidate"] = {
                    "time_seconds": peak["time_seconds"],
                    "image_motion_per_sec": peak_speed,
                    "frame_index": peak["frame_index"],
                    "label": "蹴り脚の動きのピーク候補",
                }
                later = [item for item in valid if item["frame_index"] > peak["frame_index"]]
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
        result["feet"][side] = foot_result
    result["phases"] = [
        {"key": "approach", "label": "助走", "status": "manual_review_required", "time_seconds": None},
        {"key": "plant", "label": "軸足接地", "status": "manual_review_required", "time_seconds": None},
        {"key": "swing", "label": "蹴り脚の振り出し", "status": "candidate_only", "time_source": "foot_motion_peak"},
        {"key": "impact", "label": "インパクト", "status": "manual_review_required", "time_seconds": None},
        {"key": "follow_through", "label": "フォロースルー", "status": "candidate_only", "time_source": "post_peak_motion_drop"},
    ]
    if interval > 0.75:
        result["limitations"].append("撮影・解析サンプル間隔が粗いため、動作ピーク候補を表示していません。")
    return result


def process_video(path: str, mode: str, camera_angle: str = "未選択", progress_callback=None, jersey_numbers=None):
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
    frame_idx = 0
    target_jerseys = [x.strip() for x in (jersey_numbers or "10,74").replace("；", ",").split(",") if x.strip()]
    with mp_pose.Pose(static_image_mode=(mode == "match"), model_complexity=1,
                      enable_segmentation=False, min_detection_confidence=0.5,
                      min_tracking_confidence=0.5) as pose:
        while len(frames) < max_samples:
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
                h, w = frame.shape[:2]
                if w > 960:
                    new_h = max(1, int(round(h * 960 / w)))
                    frame = cv2.resize(frame, (960, new_h), interpolation=cv2.INTER_AREA)
                metrics = analyze_frame(frame, pose)
                if metrics:
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
    # Estimate ankle/foot landmark movement between sampled frames in normalized image coordinates.
    # Values are image-widths per second, not real-world speed; camera motion and perspective affect them.
    for i, current in enumerate(frames):
        for side in ("left", "right"):
            key = side + "_foot_index"
            prev = frames[i - 1] if i > 0 else None
            a = current.get("landmarks", {}).get(key)
            b = prev.get("landmarks", {}).get(key) if prev else None
            dt = (current.get("time_seconds", 0) - prev.get("time_seconds", 0)) if prev else 0
            if a and b and dt > 0 and a[2] >= 0.5 and b[2] >= 0.5:
                current[side + "_foot_image_motion_per_sec"] = round(float(np.linalg.norm(np.array(a[:2]) - np.array(b[:2])) / dt), 4)
            else:
                current[side + "_foot_image_motion_per_sec"] = None
    kick_phase_candidates = build_kick_phase_candidates(frames, actual_interval) if mode == "form" else None
    summary = {
        "sampled_pose_frames": len(frames),
        "duration_seconds": round(duration, 2),
        "average_left_right_knee_angle_deg": round(float(np.mean(knees)), 1) if knees else None,
        "average_trunk_lean_image_angle_deg": round(float(np.mean(trunks)), 1) if trunks else None,
        "average_left_right_hip_angle_deg": round(float(np.mean(hips)), 1) if hips else None,
        "sampling_interval_seconds": round(actual_interval, 3),
        "sampling_rate_fps": round(1 / actual_interval, 2) if actual_interval > 0 else None,
        "frames": frames,
    }
    if mode == "form":
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

async def analyze_upload(file: UploadFile, mode: str):
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
            return process_video(temp_path, mode)
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
                return process_video(converted_path, mode)
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
    result = await analyze_upload(file, "form")
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
    frames = summary.get('frames', [])
    scored = []
    for frame in frames:
        speeds = [frame.get('left_foot_image_motion_per_sec'), frame.get('right_foot_image_motion_per_sec')]
        speeds = [float(v) for v in speeds if isinstance(v, (int, float))]
        if not speeds:
            continue
        score = max(speeds)
        if score > 0:
            scored.append({'time_seconds': float(frame.get('time_seconds', 0)), 'score': score})
    if len(scored) < 3:
        return []
    values = sorted(x['score'] for x in scored)
    threshold = values[min(len(values) - 1, int((len(values) - 1) * 0.75))]
    selected = [x for x in scored if x['score'] >= threshold and x['score'] > 0.015]
    selected.sort(key=lambda x: x['score'], reverse=True)
    chosen = []
    for item in selected:
        if all(abs(item['time_seconds'] - old['time_seconds']) >= 10 for old in chosen):
            chosen.append(item)
        if len(chosen) >= max_events:
            break
    chosen.sort(key=lambda x: x['time_seconds'])
    return [{'id': str(i + 1), 'time_seconds': round(x['time_seconds'], 2),
             'movement_score': round(x['score'], 4),
             'label': '動きの変化候補',
             'reason': '足先の画像上の移動量が、スキャンした場面の中で大きい時間帯です。',
             'is_football_action_confirmed': False}
            for i, x in enumerate(chosen)]

def extract_candidate_clips(video_path, job_id, candidates, duration):
    clips = []
    for event in candidates:
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
        if proc.returncode == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            clips.append({'id': event['id'], 'time_seconds': event['time_seconds'],
                          'label': event['label'], 'reason': event['reason'], 'path': clip_path})
        else:
            if os.path.exists(clip_path):
                os.remove(clip_path)
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


def _set_match_job(job_id: str, **updates):
    job = match_jobs.get(job_id)
    if job is not None:
        job.update(updates)


def run_match_job(job_id: str, source_path: str, jersey_numbers: str):
    converted_path = None
    try:
        _set_match_job(job_id, status="processing", progress=5, stage="動画を解析用MP4に変換中")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as converted:
            converted_path = converted.name
        command = [
            "ffmpeg", "-y", "-i", source_path, "-map", "0:v:0", "-an",
            "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", converted_path,
        ]
        converted_result = subprocess.run(command, capture_output=True, text=True, timeout=900)
        if converted_result.returncode != 0:
            raise RuntimeError("動画を解析用MP4に変換できませんでした。")
        _set_match_job(job_id, progress=15, stage="動画全体をスキャン中")
        def progress(value):
            _set_match_job(job_id, progress=value, stage="動画全体をスキャン中")
        result = process_video(converted_path, "match", progress_callback=progress, jersey_numbers=jersey_numbers)
        summary = result.get("summary", {})
        candidates = build_movement_candidates(summary)
        _set_match_job(job_id, progress=92, stage="動きの候補場面を短い動画に切り出し中")
        clips = extract_candidate_clips(converted_path, job_id, candidates, float(summary.get("duration_seconds", 0)))
        for event in candidates:
            matching_clip = next((x for x in clips if x["id"] == event["id"]), None)
            event["clip_available"] = matching_clip is not None
            if matching_clip:
                event["clip_url"] = f"/analyze/jobs/{job_id}/clips/{event['id']}"
                try:
                    event["dense_analysis"] = analyze_candidate_clip_dense(
                        matching_clip["path"], jersey_numbers=jersey_numbers,
                        sample_rate=1.5, max_samples=16
                    )
                except Exception as clip_exc:
                    event["dense_analysis"] = {"error": str(clip_exc), "note": "候補動画の詳細再解析は完了しませんでした。"}
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
        }
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
