"""Health check endpoints."""
from __future__ import annotations

import shutil

from fastapi import APIRouter

from app.settings import settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    """Service health check."""
    from app.main import db

    try:
        await db.get_jobs()
        db_ok = True
    except Exception:
        db_ok = False

    disk = shutil.disk_usage(str(settings.data_dir))
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
    }


@router.get("/health/selectors")
async def selector_health(plugin: str):
    """Placeholder for selector health check."""
    return {
        "plugin": plugin,
        "status": "not_implemented",
        "message": "Requires a running worker to perform selector checks",
    }
