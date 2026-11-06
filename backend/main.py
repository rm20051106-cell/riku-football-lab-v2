import os
import re
import hashlib
import asyncio
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
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from job_store import init_state_store, load_match_jobs, load_match_uploads, save_match_job, save_match_upload, delete_match_upload, cleanup_expired_match_uploads, create_match_job_for_upload, get_match_upload_completion
from video_sampling import read_sampled_frame
from upload_integrity import verify_uploaded_chunks, build_upload_resume_state, reconcile_uploaded_chunks
    try:
        invalid_chunks = reconcile_uploaded_chunks(
            upload["path"], upload["size_bytes"], upload["chunk_size_bytes"], upload["chunks"]
        )
        for invalid_index in invalid_chunks:
            upload["chunks"].pop(str(invalid_index), None)
        if invalid_chunks:
            save_match_upload(upload_id, upload)
        resume_state = build_upload_resume_state(
            upload["size_bytes"], upload["chunk_size_bytes"], upload["chunks"]
        )
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"アップロード再開情報が不正です：{exc}")
    return {
        "upload_id": upload_id,
        "size_bytes": upload["size_bytes"],
        "chunk_size_bytes": upload["chunk_size_bytes"],
        "rejected_chunks": invalid_chunks,
        **resume_state,
    }
