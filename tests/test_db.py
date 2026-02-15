"""Tests for the async SQLite database layer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime

from app.db import Database
from app.schemas import TaskRecord, JobRecord, ArtifactRecord, WorkerRecord


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.init()
    yield database
    await database.close()


def _make_job(job_id="job1"):
    now = datetime.utcnow().isoformat()
    return JobRecord(id=job_id, spec_json="{}", created_at=now, updated_at=now)


def _make_task(task_id="t1", job_id="job1", plugin="test", task_type="gen", **kwargs):
    now = datetime.utcnow().isoformat()
    defaults = dict(
        id=task_id,
        job_id=job_id,
        plugin=plugin,
        task_type=task_type,
        payload_json='{"prompt":"hi"}',
        status="queued",
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return TaskRecord(**defaults)


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    async with db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as c:
        tables = {row[0] for row in await c.fetchall()}
    assert tables >= {"tasks", "jobs", "artifacts", "workers"}


@pytest.mark.asyncio
async def test_job_roundtrip(db):
    job = _make_job()
    await db.insert_job(job)
    got = await db.get_job("job1")
    assert got is not None
    assert got.id == "job1"


@pytest.mark.asyncio
async def test_task_roundtrip(db):
    await db.insert_job(_make_job())
    task = _make_task()
    await db.insert_task(task)
    got = await db.get_task("t1")
    assert got is not None
    assert got.plugin == "test"


@pytest.mark.asyncio
async def test_claim_task(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task())
    claimed = await db.claim_task("w1", "test")
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.assigned_worker_id == "w1"
    # Second claim returns None
    assert await db.claim_task("w2", "test") is None


@pytest.mark.asyncio
async def test_claim_skips_blocked(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", status="queued"))
    await db.insert_task(_make_task("t2", depends_on_task_id="t1"))
    # t2 depends on t1 which is not completed -- should only claim t1
    claimed = await db.claim_task("w1", "test")
    assert claimed.id == "t1"
    # No more claimable
    assert await db.claim_task("w2", "test") is None


@pytest.mark.asyncio
async def test_claim_allows_completed_dep(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", status="completed"))
    await db.insert_task(_make_task("t2", depends_on_task_id="t1"))
    claimed = await db.claim_task("w1", "test")
    assert claimed is not None
    assert claimed.id == "t2"


@pytest.mark.asyncio
async def test_update_job_counts(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", status="completed"))
    await db.insert_task(_make_task("t2", status="failed"))
    await db.insert_task(_make_task("t3", status="queued"))
    await db.update_job_counts("job1")
    job = await db.get_job("job1")
    assert job.total_tasks == 3
    assert job.completed_tasks == 1
    assert job.failed_tasks == 1
    assert job.status == "active"


@pytest.mark.asyncio
async def test_update_job_counts_all_done(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", status="completed"))
    await db.insert_task(_make_task("t2", status="completed"))
    await db.update_job_counts("job1")
    job = await db.get_job("job1")
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_artifact_roundtrip(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task())
    now = datetime.utcnow().isoformat()
    art = ArtifactRecord(
        id="a1",
        job_id="job1",
        task_id="t1",
        plugin="test",
        kind="image",
        filepath="/tmp/img.png",
        created_at=now,
    )
    await db.insert_artifact(art)
    arts = await db.get_artifacts(job_id="job1")
    assert len(arts) == 1
    assert arts[0].kind == "image"


@pytest.mark.asyncio
async def test_find_duplicate(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task())
    now = datetime.utcnow().isoformat()
    art = ArtifactRecord(
        id="a1",
        job_id="job1",
        task_id="t1",
        plugin="test",
        kind="image",
        filepath="/tmp/img.png",
        sha256="abc123",
        created_at=now,
    )
    await db.insert_artifact(art)
    dup = await db.find_duplicate("job1", "abc123")
    assert dup is not None
    assert await db.find_duplicate("job1", "xyz") is None


@pytest.mark.asyncio
async def test_worker_upsert(db):
    now = datetime.utcnow().isoformat()
    w = WorkerRecord(worker_id="w1", plugin="test", registered_at=now)
    await db.upsert_worker(w)
    workers = await db.get_workers()
    assert len(workers) == 1
    # Upsert again
    w2 = WorkerRecord(worker_id="w1", plugin="test2", registered_at=now)
    await db.upsert_worker(w2)
    workers = await db.get_workers()
    assert len(workers) == 1
    assert workers[0].plugin == "test2"


@pytest.mark.asyncio
async def test_get_jobs(db):
    await db.insert_job(_make_job("job1"))
    await db.insert_job(_make_job("job2"))
    jobs = await db.get_jobs()
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_get_tasks_with_filters(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", status="queued", plugin="test"))
    await db.insert_task(_make_task("t2", status="running", plugin="test"))
    await db.insert_task(_make_task("t3", status="queued", plugin="other"))

    # Filter by status
    queued = await db.get_tasks(status="queued")
    assert len(queued) == 2

    # Filter by plugin
    test_tasks = await db.get_tasks(plugin="test")
    assert len(test_tasks) == 2

    # Filter by both
    filtered = await db.get_tasks(status="queued", plugin="test")
    assert len(filtered) == 1
    assert filtered[0].id == "t1"


@pytest.mark.asyncio
async def test_get_tasks_by_ref_id(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1", ref_id="group-a"))
    await db.insert_task(_make_task("t2", ref_id="group-a"))
    await db.insert_task(_make_task("t3", ref_id="group-b"))
    tasks = await db.get_tasks_by_ref_id("job1", "group-a")
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_update_task(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task())
    await db.update_task("t1", status="running", assigned_worker_id="w1")
    task = await db.get_task("t1")
    assert task.status == "running"
    assert task.assigned_worker_id == "w1"


@pytest.mark.asyncio
async def test_update_job(db):
    await db.insert_job(_make_job())
    await db.update_job("job1", status="failed")
    job = await db.get_job("job1")
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_get_artifact_by_id(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task())
    now = datetime.utcnow().isoformat()
    art = ArtifactRecord(
        id="a1",
        job_id="job1",
        task_id="t1",
        plugin="test",
        kind="image",
        filepath="/tmp/img.png",
        created_at=now,
    )
    await db.insert_artifact(art)
    got = await db.get_artifact("a1")
    assert got is not None
    assert got.filepath == "/tmp/img.png"
    assert await db.get_artifact("nonexistent") is None


@pytest.mark.asyncio
async def test_get_stale_tasks(db):
    await db.insert_job(_make_job())
    # Create a task with an old heartbeat
    await db.insert_task(
        _make_task("t1", status="running", heartbeat_at="2000-01-01T00:00:00")
    )
    # Create a task with a recent heartbeat
    await db.insert_task(
        _make_task("t2", status="running", heartbeat_at=datetime.utcnow().isoformat())
    )
    stale = await db.get_stale_tasks(timeout_seconds=120)
    assert len(stale) == 1
    assert stale[0].id == "t1"


@pytest.mark.asyncio
async def test_update_worker_heartbeat(db):
    now = datetime.utcnow().isoformat()
    w = WorkerRecord(worker_id="w1", plugin="test", registered_at=now)
    await db.upsert_worker(w)
    await db.update_worker_heartbeat("w1")
    workers = await db.get_workers()
    assert workers[0].last_seen_at is not None


@pytest.mark.asyncio
async def test_get_artifacts_by_task_and_kind(db):
    await db.insert_job(_make_job())
    await db.insert_task(_make_task("t1"))
    await db.insert_task(_make_task("t2"))
    now = datetime.utcnow().isoformat()
    await db.insert_artifact(
        ArtifactRecord(
            id="a1", job_id="job1", task_id="t1", plugin="test",
            kind="image", filepath="/tmp/img1.png", created_at=now,
        )
    )
    await db.insert_artifact(
        ArtifactRecord(
            id="a2", job_id="job1", task_id="t1", plugin="test",
            kind="pdf", filepath="/tmp/doc.pdf", created_at=now,
        )
    )
    await db.insert_artifact(
        ArtifactRecord(
            id="a3", job_id="job1", task_id="t2", plugin="test",
            kind="image", filepath="/tmp/img2.png", created_at=now,
        )
    )

    # Filter by task_id
    t1_arts = await db.get_artifacts(task_id="t1")
    assert len(t1_arts) == 2

    # Filter by kind
    images = await db.get_artifacts(kind="image")
    assert len(images) == 2

    # Filter by both
    t1_images = await db.get_artifacts(task_id="t1", kind="image")
    assert len(t1_images) == 1
