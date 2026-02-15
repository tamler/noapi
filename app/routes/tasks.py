"""Task management endpoints: list, claim, heartbeat, complete, fail, retry."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.schemas import ClaimRequest, CompleteRequest, FailRequest, HeartbeatRequest
from app.services.pipeline import PipelineResolver

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
async def list_tasks(
    job_id: str | None = None,
    status: str | None = None,
    plugin: str | None = None,
):
    """List tasks with optional filters."""
    from app.main import db

    tasks = await db.get_tasks(job_id=job_id, status=status, plugin=plugin)
    return [t.model_dump() for t in tasks]


@router.post("/tasks/claim")
async def claim_task(req: ClaimRequest):
    """Atomically claim a queued task for a worker."""
    from app.main import db

    task = await db.claim_task(worker_id=req.worker_id, plugin=req.plugin)
    if not task:
        return {"status": "no_tasks"}
    return {"status": "claimed", "task": task.model_dump()}


@router.post("/tasks/{task_id}/heartbeat")
async def heartbeat(task_id: str, req: HeartbeatRequest):
    """Worker heartbeat to indicate task is still being processed."""
    from app.main import db

    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task '{task_id}' not found")
    if task.status != "running":
        raise HTTPException(409, f"Task is not running (status={task.status})")

    now = datetime.now(timezone.utc).isoformat()
    await db.update_task(task_id, heartbeat_at=now)
    await db.update_worker_heartbeat(req.worker_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, req: CompleteRequest):
    """Mark a task as completed and trigger downstream pipeline tasks."""
    from app.main import db

    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task '{task_id}' not found")
    if task.status != "running":
        raise HTTPException(409, f"Task is not running (status={task.status})")

    # 1. Mark task completed
    now = datetime.now(timezone.utc).isoformat()
    await db.update_task(
        task_id,
        status="completed",
        last_error=None,
    )

    # 2. Update job counts
    await db.update_job_counts(task.job_id)

    # 3. Check for downstream pipeline tasks
    job = await db.get_job(task.job_id)
    if job:
        # Reload task to get updated status
        completed_task = await db.get_task(task_id)
        resolver = PipelineResolver(db)
        new_tasks = await resolver.check_pipelines(completed_task, job)

        # 4. If new tasks were created, update counts again
        if new_tasks:
            await db.update_job_counts(task.job_id)

    # 5. Unblock dependent tasks
    blocked_tasks = await db.get_tasks(job_id=task.job_id, status="blocked")
    for blocked in blocked_tasks:
        if blocked.depends_on_task_id == task_id:
            await db.update_task(blocked.id, status="queued")

    return {"status": "completed", "new_tasks_created": len(new_tasks) if job else 0}


@router.post("/tasks/{task_id}/fail")
async def fail_task(task_id: str, req: FailRequest):
    """Mark a task as failed, needs_human, or re-queue for retry."""
    from app.main import db

    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task '{task_id}' not found")

    if req.needs_human:
        await db.update_task(
            task_id,
            status="needs_human",
            last_error=req.error,
        )
    elif task.attempts + 1 < task.max_attempts:
        await db.update_task(
            task_id,
            status="queued",
            attempts=task.attempts + 1,
            last_error=req.error,
            assigned_worker_id=None,
            heartbeat_at=None,
        )
    else:
        await db.update_task(
            task_id,
            status="failed",
            attempts=task.attempts + 1,
            last_error=req.error,
        )

    await db.update_job_counts(task.job_id)

    updated = await db.get_task(task_id)
    return {"status": updated.status, "attempts": updated.attempts}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """Reset a needs_human or failed task back to queued."""
    from app.main import db

    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task '{task_id}' not found")
    if task.status not in ("needs_human", "failed"):
        raise HTTPException(
            409,
            f"Task cannot be retried (status={task.status})",
        )

    await db.update_task(
        task_id,
        status="queued",
        last_error=None,
        assigned_worker_id=None,
        heartbeat_at=None,
    )
    await db.update_job_counts(task.job_id)
    return {"status": "queued"}
