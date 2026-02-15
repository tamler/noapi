"""Artifact listing, download, and upload endpoints."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.qc.basic import compute_sha256, generate_artifact_filename
from app.schemas import ArtifactRecord
from app.settings import settings

router = APIRouter(prefix="/api", tags=["artifacts"])

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_VIDEO_EXTS = {".mp4", ".webm"}


def _determine_kind(filename: str) -> str:
    """Fallback: determine artifact kind from file extension."""
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    return "other"


@router.get("/artifacts")
async def list_artifacts(
    job_id: str | None = None,
    task_id: str | None = None,
    kind: str | None = None,
):
    """List artifacts with optional filters."""
    from app.main import db

    artifacts = await db.get_artifacts(job_id=job_id, task_id=task_id, kind=kind)
    return [a.model_dump() for a in artifacts]


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """Download an artifact file."""
    from app.main import db

    artifact = await db.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(404, f"Artifact '{artifact_id}' not found")

    filepath = Path(artifact.filepath)
    if not filepath.exists():
        raise HTTPException(404, "Artifact file not found on disk")

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type="application/octet-stream",
    )


@router.post("/upload/{job_id}/{task_id}")
async def upload_artifacts(
    job_id: str,
    task_id: str,
    files: List[UploadFile] = File(...),
    artifacts_manifest: str = Form("[]"),
    task_metadata: str = Form("{}"),
):
    """Upload artifact files for a task.

    files: one or more artifact files.
    artifacts_manifest: JSON array parallel to files. Each entry:
        {"kind": "image", "filename_hint": "...", "metadata": {...}}
    task_metadata: JSON object with task-level metadata from FlowResult.
    """
    from app.main import db

    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task '{task_id}' not found")

    try:
        manifest = json.loads(artifacts_manifest)
    except json.JSONDecodeError:
        manifest = []

    try:
        task_meta = json.loads(task_metadata)
    except json.JSONDecodeError:
        task_meta = {}

    # Determine naming prefix
    from app.schemas import JobSpec
    spec = JobSpec.model_validate_json(job.spec_json)
    naming_prefix = spec.naming_prefix or job.project_name or "artifact"

    # Count existing artifacts for variant numbering
    existing = await db.get_artifacts(task_id=task_id)
    variant_offset = len(existing)

    results = []
    for idx, file in enumerate(files):
        # Get manifest entry for this file (or use defaults)
        entry = manifest[idx] if idx < len(manifest) else {}
        kind = entry.get("kind") or _determine_kind(file.filename or "unknown")
        filename_hint = entry.get("filename_hint")
        artifact_metadata = entry.get("metadata", {})

        original_filename = file.filename or "unknown"

        # Create artifact directory: data/jobs/{job_id}/artifacts/{kind}/
        artifact_dir = settings.jobs_dir / job_id / "artifacts" / kind
        artifact_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(original_filename).suffix.lower() or ".bin"
        temp_path = artifact_dir / f"_tmp_{uuid.uuid4()}{ext}"
        try:
            content = await file.read()
            with open(temp_path, "wb") as f:
                f.write(content)

            sha256 = compute_sha256(temp_path)
            file_size = temp_path.stat().st_size

            # Duplicate detection within the same job
            duplicate = await db.find_duplicate(job_id, sha256)
            is_duplicate = duplicate is not None

            # Deterministic filename (core owns naming)
            variant = variant_offset + idx
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            final_name = generate_artifact_filename(
                naming_prefix=naming_prefix,
                plugin=task.plugin,
                task_type=task.task_type,
                variant=variant,
                sha256=sha256,
                timestamp=timestamp,
                extension=ext.lstrip("."),
            )
            final_path = artifact_dir / final_name
            os.rename(str(temp_path), str(final_path))

            # Sidecar JSON
            sidecar = {
                "job_id": job_id,
                "task_id": task_id,
                "plugin": task.plugin,
                "task_type": task.task_type,
                "original_filename": original_filename,
                "filename_hint": filename_hint,
                "sha256": sha256,
                "file_size_bytes": file_size,
                "is_duplicate": is_duplicate,
                "kind": kind,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "task_metadata": task_meta,
                "artifact_metadata": artifact_metadata,
            }
            sidecar_path = final_path.with_suffix(final_path.suffix + ".json")
            with open(sidecar_path, "w") as sf:
                json.dump(sidecar, sf, indent=2)

            # DB record
            artifact_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # Merge artifact-level + task-level metadata into stored metadata
            stored_metadata = {
                "filename_hint": filename_hint,
                "artifact_metadata": artifact_metadata,
                "task_metadata": task_meta,
            }

            artifact = ArtifactRecord(
                id=artifact_id,
                job_id=job_id,
                task_id=task_id,
                plugin=task.plugin,
                kind=kind,
                filepath=str(final_path),
                original_filename=original_filename,
                sha256=sha256,
                file_size_bytes=file_size,
                is_duplicate=is_duplicate,
                metadata_json=json.dumps(stored_metadata),
                created_at=now,
            )
            await db.insert_artifact(artifact)

            results.append({
                "artifact_id": artifact_id,
                "filename": final_name,
                "kind": kind,
                "is_duplicate": is_duplicate,
                "sha256": sha256,
                "file_size_bytes": file_size,
            })
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    return {"status": "uploaded", "artifacts": results}
