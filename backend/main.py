import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

APP_NAME = "RIKU FOOTBALL LAB Free AI Analysis API"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))
MAX_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "180"))

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

def angle(a, b, c):
    a, b, c = np.array(a, dtype=float), np.array(b, dtype=float), np.array(c, dtype=float)
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
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = pose.process(rgb)
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks.landmark
    def p(name):
        v = lm[mp_pose.PoseLandmark[name].value]
        return [float(v.x), float(v.y), float(v.visibility)]
    visible = sum(1 for v in lm if v.visibility >= 0.5)
    left_knee = angle(p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2], p("LEFT_ANKLE")[:2])
    right_knee = angle(p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2], p("RIGHT_ANKLE")[:2])
    left_hip = angle(p("LEFT_SHOULDER")[:2], p("LEFT_HIP")[:2], p("LEFT_KNEE")[:2])
    right_hip = angle(p("RIGHT_SHOULDER")[:2], p("RIGHT_HIP")[:2], p("RIGHT_KNEE")[:2])
    shoulder_mid = [(p("LEFT_SHOULDER")[0] + p("RIGHT_SHOULDER")[0]) / 2,
                    (p("LEFT_SHOULDER")[1] + p("RIGHT_SHOULDER")[1]) / 2]
    hip_mid = [(p("LEFT_HIP")[0] + p("RIGHT_HIP")[0]) / 2,
               (p("LEFT_HIP")[1] + p("RIGHT_HIP")[1]) / 2]
    # Image-space trunk lean estimate; camera angle and perspective affect this.
    trunk_dx = shoulder_mid[0] - hip_mid[0]
    trunk_dy = shoulder_mid[1] - hip_mid[1]
    trunk_angle = round(float(np.degrees(np.arctan2(abs(trunk_dx), max(1e-6, abs(trunk_dy))))), 1)
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
        "left_knee_angle_deg": left_knee,
        "right_knee_angle_deg": right_knee,
        "left_hip_angle_deg": left_hip,
        "right_hip_angle_deg": right_hip,
        "trunk_lean_image_angle_deg": trunk_angle,
        "landmarks": landmarks,
    }

def process_video(path: str, mode: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="動画を開けませんでした。MP4など一般的な形式でお試しください。")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0
    if duration > MAX_SECONDS:
        cap.release()
        raise HTTPException(status_code=413, detail=f"動画が長すぎます。無料枠では{MAX_SECONDS}秒以内にしてください。")
    # Sample up to three times per second. This is still a pose trend, not true ball-contact detection.
    target_sample_rate = 3.0
    interval = max(1, int(round(fps / target_sample_rate))) if fps > 0 else 8
    actual_interval = interval / fps if fps > 0 else 1 / target_sample_rate
    max_samples = 360
    frames = []
    frame_idx = 0
    with mp_pose.Pose(static_image_mode=False, model_complexity=1,
                      enable_segmentation=False, min_detection_confidence=0.5,
                      min_tracking_confidence=0.5) as pose:
        while len(frames) < max_samples:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % interval == 0:
                metrics = analyze_frame(frame, pose)
                if metrics:
                    frames.append({"time_seconds": round(frame_idx / fps, 2) if fps > 0 else frame_idx,
                                   **metrics})
            frame_idx += 1
    cap.release()
    if not frames:
        raise HTTPException(status_code=422, detail="人物の姿勢を検出できませんでした。人物全身が見える明るい動画で再試行してください。")
    knees = [x[k] for x in frames for k in ("left_knee_angle_deg", "right_knee_angle_deg") if x.get(k) is not None]
    trunks = [x["trunk_lean_image_angle_deg"] for x in frames]
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
        tips = []
        if summary["average_left_right_knee_angle_deg"] is not None:
            tips.append("膝角度は映像上の推定値です。蹴る瞬間の軸足・膝の曲がりを、正面と横からの動画で比較してください。")
        if summary["average_left_right_hip_angle_deg"] is not None:
            tips.append("股関節角度（左右平均・画像上の推定）も算出しました。蹴る直前からインパクト後までの変化を確認してください。")
        tips.append("体幹の傾きは画像上の推定値です。カメラ位置・遠近・選手の向きで変わるため、数値だけで良し悪しを断定しません。")
        tips.append("足先の画像上の移動量も参考値として算出しますが、実速度ではありません。カメラ移動・遠近・遮蔽の影響を受けます。")
        tips.append("この解析では軸足とボールの距離、足とボールの接触位置、インパクト時刻、キック速度、狙ったコースは自動判定していません。")
        summary["feedback"] = tips
    else:
        summary["feedback"] = [
            "この無料版は動画から姿勢をサンプリングします。背番号のOCR認識・選手の個体識別・追跡・プレーの意味理解はまだ実装していません。",
            "背番号による自動抽出を行うには、別の人物検出・ユニフォーム番号認識・追跡モデルを追加して精度検証する必要があります。"
        ]
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
async def analyze_form(file: UploadFile = File(...), kick_type: str = Form("シュート"), dominant_foot: str = Form("右足")):
    result = await analyze_upload(file, "form")
    result["kick_type"] = kick_type
    result["dominant_foot"] = dominant_foot
    return result

@app.post("/analyze/match")
async def analyze_match(file: UploadFile = File(...), jersey_numbers: str = Form("10,74")):
    result = await analyze_upload(file, "match")
    result["requested_jersey_numbers"] = jersey_numbers
    return result
