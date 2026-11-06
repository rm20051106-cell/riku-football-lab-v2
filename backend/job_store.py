"""Small SQLite-backed persistence for match jobs and resumable uploads.

The default database lives in the container's writable temporary directory.
Set RIKU_STATE_DB to a path on a persistent mounted volume when one is available.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/tmp/riku-football-lab-state.sqlite3"


def _db_path() -> str:
    path = Path(os.getenv("RIKU_STATE_DB", DEFAULT_DB_PATH)).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def _connect():
    connection = sqlite3.connect(_db_path(), timeout=15)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
        connection.execute("""
            CREATE TABLE IF NOT EXISTS match_upload_completions (
                upload_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
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



def create_match_job_for_upload(upload_id: str, job: dict) -> tuple[str, bool]:
    """Atomically persist one job per upload session; repeated completion is idempotent."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT job_id FROM match_upload_completions WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
        if row:
            return str(row[0]), False
        job_id = str(job["job_id"])
        connection.execute(
            "INSERT INTO match_jobs(job_id, payload, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP)",
            (job_id, _encode(job)),
        )
        connection.execute(
            "INSERT INTO match_upload_completions(upload_id, job_id, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP)",
            (upload_id, job_id),
        )
        return job_id, True


def get_match_upload_completion(upload_id: str) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT job_id FROM match_upload_completions WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
    return str(row[0]) if row else None


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
            if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"].strip():
                # Keep the session even if its ephemeral video file vanished. The upload
                # resume endpoint recreates the sparse file and marks old chunks missing.
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



def cleanup_expired_match_uploads(max_age_hours: int = 24) -> list[str]:
    """Delete abandoned temporary upload sessions and return their file paths."""
    hours = max(1, int(max_age_hours))
    with _connect() as connection:
        rows = connection.execute(
            "SELECT upload_id, payload FROM match_uploads "
            "WHERE updated_at < datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchall()
        paths = []
        for upload_id, payload in rows:
            try:
                item = json.loads(payload)
                path = item.get("path") if isinstance(item, dict) else None
                if path:
                    paths.append(str(path))
            except (TypeError, ValueError):
                pass
            connection.execute("DELETE FROM match_uploads WHERE upload_id = ?", (upload_id,))
    return paths
