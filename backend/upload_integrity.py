"""Streaming integrity checks for assembled resumable video uploads."""
import hashlib
import os
import re


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_sha256(value) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def verify_uploaded_chunks(path: str, total_size: int, chunk_size: int, chunks: dict) -> None:
    """Raise ValueError if assembled bytes differ from the acknowledged chunk hashes."""
    if total_size <= 0 or chunk_size <= 0:
        raise ValueError("invalid upload size")
    if os.path.getsize(path) != total_size:
        raise ValueError("assembled file size mismatch")
    expected_count = (total_size + chunk_size - 1) // chunk_size
    if not isinstance(chunks, dict) or len(chunks) != expected_count:
        raise ValueError("chunk metadata count mismatch")
    with open(path, "rb") as source:
        for index in range(expected_count):
            metadata = chunks.get(str(index))
            if not isinstance(metadata, dict):
                raise ValueError(f"missing chunk metadata: {index}")
            expected_size = min(chunk_size, total_size - index * chunk_size)
            if metadata.get("size_bytes") != expected_size:
                raise ValueError(f"chunk size metadata mismatch: {index}")
            expected_digest = metadata.get("sha256")
            if not _valid_sha256(expected_digest):
                raise ValueError(f"invalid chunk SHA-256 metadata: {index}")
            digest = hashlib.sha256()
            remaining = expected_size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError(f"truncated chunk: {index}")
                digest.update(block)
                remaining -= len(block)
            if digest.hexdigest() != expected_digest:
                raise ValueError(f"chunk SHA-256 mismatch: {index}")


def reconcile_uploaded_chunks(path: str, total_size: int, chunk_size: int, chunks: dict) -> list:
    """Return acknowledged chunk indexes whose on-disk bytes no longer match metadata."""
    if total_size <= 0 or chunk_size <= 0 or not isinstance(chunks, dict):
        raise ValueError("invalid upload dimensions or metadata")
    invalid = []
    try:
        source = open(path, "rb")
    except OSError:
        return sorted(int(index) for index in chunks if str(index).isdigit())
    with source:
        for raw_index, metadata in list(chunks.items()):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                raise ValueError("invalid chunk index")
            if index < 0 or str(index) != str(raw_index):
                raise ValueError("invalid chunk index")
            expected_size = min(chunk_size, total_size - index * chunk_size)
            if (index * chunk_size >= total_size or not isinstance(metadata, dict)
                    or metadata.get("size_bytes") != expected_size
                    or not _valid_sha256(metadata.get("sha256"))):
                raise ValueError(f"invalid chunk metadata: {index}")
            source.seek(index * chunk_size)
            data = source.read(expected_size)
            if len(data) != expected_size or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                invalid.append(index)
    return invalid


def build_upload_resume_state(total_size: int, chunk_size: int, chunks: dict) -> dict:
    """Return authoritative server-side chunk receipt and resume metadata."""
    try:
        total_size = int(total_size)
        chunk_size = int(chunk_size)
    except (TypeError, ValueError):
        raise ValueError("invalid upload dimensions")
    if total_size <= 0 or chunk_size <= 0:
        raise ValueError("upload dimensions must be positive")
    if not isinstance(chunks, dict):
        raise ValueError("invalid chunk metadata")
    total_chunks = (total_size + chunk_size - 1) // chunk_size
    received = []
    received_bytes = 0
    for raw_index, metadata in chunks.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError("invalid chunk index")
        if index < 0 or index >= total_chunks or str(index) != str(raw_index):
            raise ValueError("chunk index out of range")
        expected_size = min(chunk_size, total_size - index * chunk_size)
        if not isinstance(metadata, dict) or metadata.get("size_bytes") != expected_size:
            raise ValueError("chunk metadata size mismatch")
        if not _valid_sha256(metadata.get("sha256")):
            raise ValueError(f"invalid chunk SHA-256 metadata: {index}")
        received.append(index)
        received_bytes += expected_size
    received.sort()
    received_set = set(received)
    missing = [index for index in range(total_chunks) if index not in received_set]
    return {
        "total_chunks": total_chunks,
        "received_chunks": received,
        "received_chunk_sha256": {
            str(index): chunks[str(index)]["sha256"]
            for index in received
        },
        "missing_chunks": missing,
        "received_bytes": received_bytes,
        "confirmed_percent": int(received_bytes * 100 / total_size),
    }
