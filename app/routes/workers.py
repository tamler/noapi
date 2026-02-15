"""Worker registration and listing endpoints."""
from __future__ import annotations

import json

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import WorkerRecord, WorkerRegisterRequest

router = APIRouter(prefix="/api", tags=["workers"])


@router.post("/workers/register")
async def register_worker(req: WorkerRegisterRequest):
    """Register a worker. Optionally register its plugin manifest."""
    from app.main import db, registry

    now = datetime.now(timezone.utc).isoformat()
    worker = WorkerRecord(
        worker_id=req.worker_id,
        hostname=req.hostname,
        plugin=req.plugin,
        capabilities_json=json.dumps(req.capabilities) if req.capabilities else None,
        last_seen_at=now,
        registered_at=now,
    )
    await db.upsert_worker(worker)
    if req.manifest_json:
        registry.register(req.manifest_json)
    return {"status": "registered", "worker_id": req.worker_id}


@router.get("/workers")
async def list_workers():
    """List all registered workers."""
    from app.main import db

    workers = await db.get_workers()
    return [w.model_dump() for w in workers]
