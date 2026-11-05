"""Small SQLite-backed persistence for match jobs and resumable uploads.

The default database lives in the container's writable temporary directory.
Set RIKU_STATE_DB to a path on a persistent mounted volume when one is available.
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/tmp/riku-football-lab-state.sqlite3"


def _db_path() -> str:
    path = os.getenv("RIKU_STATE_DB", DEFAULT_DB_PATH)
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect():
    connection = sqlite3.connect(_db_path(), timeout=15)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def init_state_store() -> None:
    with _connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS match_jobs (
                job_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS match_uploads (
                upload_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def save_match_job(job_id: str, job: dict) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO match_jobs(job_id, payload, updated_at)
               VALUES(?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(job_id) DO UPDATE SET
                 payload=excluded.payload, updated_at=CURRENT_TIMESTAMP""",
            (job_id, _encode(job)),
        )


def load_match_jobs() -> dict:
    with _connect() as connection:
        rows = connection.execute("SELECT job_id, payload FROM match_jobs").fetchall()
    restored = {}
    for job_id, payload in rows:
        try:
            item = json.loads(payload)
            if isinstance(item, dict):
                restored[job_id] = item
        except (TypeError, ValueError):
            continue
    return restored


def save_match_upload(upload_id: str, upload: dict) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO match_uploads(upload_id, payload, updated_at)
               VALUES(?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(upload_id) DO UPDATE SET
                 payload=excluded.payload, updated_at=CURRENT_TIMESTAMP""",
            (upload_id, _encode(upload)),
        )


def load_match_uploads() -> dict:
    with _connect() as connection:
        rows = connection.execute("SELECT upload_id, payload FROM match_uploads").fetchall()
    restored = {}
    for upload_id, payload in rows:
        try:
            item = json.loads(payload)
            if isinstance(item, dict) and os.path.isfile(item.get("path", "")):
                restored[upload_id] = item
        except (TypeError, ValueError):
            continue
    return restored


def delete_match_upload(upload_id: str) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM match_uploads WHERE upload_id = ?", (upload_id,))


def delete_match_job(job_id: str) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM match_jobs WHERE job_id = ?", (job_id,))
