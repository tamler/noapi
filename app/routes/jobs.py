"""Job submission, listing, detail, and cancellation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import JobSpec
from app.services.scheduler import Scheduler

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/jobs")
async def submit_job(spec: JobSpec):
    """Submit a new job from a job spec."""
    from app.main import db, registry

    scheduler = Scheduler(db, registry)
    try:
        job = await scheduler.schedule_job(spec)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return job.model_dump()


@router.get("/jobs")
async def list_jobs():
    """List all jobs."""
    from app.main import db

    jobs = await db.get_jobs()
    return [j.model_dump() for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job detail."""
    from app.main import db

    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return job.model_dump()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a job: set all queued/blocked tasks to cancelled, update job status."""
    from app.main import db

    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    # Cancel all queued and blocked tasks
    tasks = await db.get_tasks(job_id=job_id)
    cancelled_count = 0
    for task in tasks:
        if task.status in ("queued", "blocked"):
            await db.update_task(task.id, status="cancelled")
            cancelled_count += 1

    # Update job status
    await db.update_job(job_id, status="cancelled")
    await db.update_job_counts(job_id)

    return {
        "status": "cancelled",
        "job_id": job_id,
        "tasks_cancelled": cancelled_count,
    }
