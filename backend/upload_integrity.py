"""Streaming integrity checks for assembled resumable video uploads."""
import hashlib
import os


def verify_uploaded_chunks(path: str, total_size: int, chunk_size: int, chunks: dict) -> None:
    """Raise ValueError if assembled bytes differ from the acknowledged chunk hashes."""
    if total_size <= 0 or chunk_size <= 0:
        raise ValueError("invalid upload size")
    if os.path.getsize(path) != total_size:
        raise ValueError("assembled file size mismatch")
    expected_count = (total_size + chunk_size - 1) // chunk_size
    if len(chunks) != expected_count:
        raise ValueError("chunk metadata count mismatch")
    with open(path, "rb") as source:
        for index in range(expected_count):
            metadata = chunks.get(str(index))
            if not isinstance(metadata, dict):
                raise ValueError(f"missing chunk metadata: {index}")
            expected_size = min(chunk_size, total_size - index * chunk_size)
            if metadata.get("size_bytes") != expected_size:
                raise ValueError(f"chunk size metadata mismatch: {index}")
            digest = hashlib.sha256()
            remaining = expected_size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError(f"truncated chunk: {index}")
                digest.update(block)
                remaining -= len(block)
            if digest.hexdigest() != metadata.get("sha256"):
                raise ValueError(f"chunk SHA-256 mismatch: {index}")


def build_upload_resume_state(total_size: int, chunk_size: int, chunks: dict) -> dict:
    """Return authoritative server-side chunk receipt and resume metadata."""
    try:
        total_size = int(total_size)
        chunk_size = int(chunk_size)
    except (TypeError, ValueError):
        raise ValueError("invalid upload dimensions")
    if total_size <= 0 or chunk_size <= 0:
        raise ValueError("upload dimensions must be positive")
    total_chunks = (total_size + chunk_size - 1) // chunk_size
    received = []
    received_bytes = 0
    for raw_index, metadata in (chunks or {}).items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError("invalid chunk index")
        if index < 0 or index >= total_chunks or str(index) != str(raw_index):
            raise ValueError("chunk index out of range")
        expected_size = min(chunk_size, total_size - index * chunk_size)
        if not isinstance(metadata, dict) or int(metadata.get("size_bytes", -1)) != expected_size:
            raise ValueError("chunk metadata size mismatch")
        received.append(index)
        received_bytes += expected_size
    received.sort()
    missing = [index for index in range(total_chunks) if index not in set(received)]
    return {
        "total_chunks": total_chunks,
        "received_chunks": received,
        "received_chunk_sha256": {
            str(index): str((chunks[str(index)]).get("sha256", ""))
            for index in received
        },
        "missing_chunks": missing,
        "received_bytes": received_bytes,
        "confirmed_percent": int(received_bytes * 100 / total_size),
    }

