FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg tesseract-ocr libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN mkdir -p /app/models && curl -fL --retry 3 --retry-delay 2 -o /app/models/pose_landmarker_lite.task https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from mediapipe.tasks import python as mp_python; from mediapipe.tasks.python import vision; p=vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(base_options=mp_python.BaseOptions(model_asset_path='/app/models/pose_landmarker_lite.task'), running_mode=vision.RunningMode.VIDEO, num_poses=8)); p.close(); print('Multi-pose model loaded successfully')"
COPY main.py job_store.py video_sampling.py upload_integrity.py .
EXPOSE 10000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
