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
