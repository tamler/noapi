"""Plugin manifest endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["plugins"])


@router.get("/plugins")
async def list_plugins():
    """List all registered plugin manifests."""
    from app.main import registry

    return registry.list_all()


@router.get("/plugins/{name}")
async def get_plugin(name: str):
    """Get a specific plugin manifest by name."""
    from app.main import registry

    manifest = registry.get(name)
    if not manifest:
        raise HTTPException(404, f"Plugin '{name}' not found")
    return manifest
