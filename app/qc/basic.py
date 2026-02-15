"""Quality control utilities for artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_sha256(filepath: str | Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check_file_size(filepath: str | Path, min_bytes: int = 1000) -> bool:
    """Return True if file is above minimum size threshold. False = suspicious."""
    return Path(filepath).stat().st_size >= min_bytes


def generate_artifact_filename(
    naming_prefix: str,
    plugin: str,
    task_type: str,
    variant: int,
    sha256: str,
    timestamp: str,
    extension: str,
) -> str:
    """Generate deterministic artifact filename."""
    hash8 = sha256[:8]
    return f"{naming_prefix}_{plugin}_{task_type}_{variant:03d}_{hash8}_{timestamp}.{extension}"
