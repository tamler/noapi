"""Async SQLite database layer for noapi."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from app.schemas import ArtifactRecord, JobRecord, TaskRecord, WorkerRecord

_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    plugin TEXT NOT NULL,
    task_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    depends_on_task_id TEXT,
    ref_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    assigned_worker_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    heartbeat_at TEXT
);
"""

_TASKS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id);
CREATE INDEX IF NOT EXISTS idx_tasks_plugin ON tasks(plugin);
CREATE INDEX IF NOT EXISTS idx_tasks_ref_id ON tasks(ref_id);
"""

_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_name TEXT,
    spec_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    total_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_ARTIFACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    plugin TEXT NOT NULL,
    kind TEXT NOT NULL,
    filepath TEXT NOT NULL,
    original_filename TEXT,
    sha256 TEXT,
    file_size_bytes INTEGER,
    is_duplicate BOOLEAN DEFAULT FALSE,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
"""

_ARTIFACTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_artifacts_job_id ON artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON artifacts(task_id);
"""

_WORKERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    hostname TEXT,
    plugin TEXT,
    capabilities_json TEXT,
    last_seen_at TEXT,
    registered_at TEXT NOT NULL
);
"""


class Database:
    """Async SQLite database wrapper for noapi."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open connection and create all tables."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

        await self._db.executescript(
            _TASKS_SCHEMA
            + _TASKS_INDEXES
            + _JOBS_SCHEMA
            + _ARTIFACTS_SCHEMA
            + _ARTIFACTS_INDEXES
            + _WORKERS_SCHEMA
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # -------------------------------------------------------------------
    # Jobs
    # -------------------------------------------------------------------

    async def insert_job(self, job: JobRecord) -> None:
        await self._db.execute(
            """INSERT INTO jobs (id, project_name, spec_json, status,
               total_tasks, completed_tasks, failed_tasks, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.project_name,
                job.spec_json,
                job.status,
                job.total_tasks,
                job.completed_tasks,
                job.failed_tasks,
                job.created_at,
                job.updated_at,
            ),
        )
        await self._db.commit()

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._db.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_job(row)
        return None

    async def get_jobs(self) -> list[JobRecord]:
        async with self._db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    async def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [job_id]
        await self._db.execute(
            f"UPDATE jobs SET {set_clause} WHERE id=?", values
        )
        await self._db.commit()

    async def update_job_counts(self, job_id: str) -> None:
        """Recount completed/failed tasks and update job. Also check if all done."""
        now = datetime.utcnow().isoformat()
        async with self._db.execute(
            "SELECT status, COUNT(*) FROM tasks WHERE job_id=? GROUP BY status",
            (job_id,),
        ) as cursor:
            counts = dict(await cursor.fetchall())
        total = sum(counts.values())
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        status = "active"
        if total > 0 and (completed + failed) == total:
            status = "completed" if failed == 0 else "failed"
        await self._db.execute(
            "UPDATE jobs SET total_tasks=?, completed_tasks=?, failed_tasks=?, status=?, updated_at=? WHERE id=?",
            (total, completed, failed, status, now, job_id),
        )
        await self._db.commit()

    # -------------------------------------------------------------------
    # Tasks
    # -------------------------------------------------------------------

    async def insert_task(self, task: TaskRecord) -> None:
        await self._db.execute(
            """INSERT INTO tasks (id, job_id, plugin, task_type, payload_json,
               status, depends_on_task_id, ref_id, attempts, max_attempts,
               last_error, assigned_worker_id, created_at, updated_at, heartbeat_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.job_id,
                task.plugin,
                task.task_type,
                task.payload_json,
                task.status,
                task.depends_on_task_id,
                task.ref_id,
                task.attempts,
                task.max_attempts,
                task.last_error,
                task.assigned_worker_id,
                task.created_at,
                task.updated_at,
                task.heartbeat_at,
            ),
        )
        await self._db.commit()

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self._db.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_task(row)
        return None

    async def get_tasks(
        self,
        job_id: str | None = None,
        status: str | None = None,
        plugin: str | None = None,
    ) -> list[TaskRecord]:
        conditions = []
        params = []
        if job_id is not None:
            conditions.append("job_id=?")
            params.append(job_id)
        if status is not None:
            conditions.append("status=?")
            params.append(status)
        if plugin is not None:
            conditions.append("plugin=?")
            params.append(plugin)

        where = " AND ".join(conditions) if conditions else "1=1"
        async with self._db.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY created_at ASC", params
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def claim_task(self, worker_id: str, plugin: str) -> TaskRecord | None:
        """Atomically claim a queued task whose dependencies are met."""
        now = datetime.utcnow().isoformat()
        async with self._db.execute(
            """
            UPDATE tasks SET status='running', assigned_worker_id=?, heartbeat_at=?, updated_at=?
            WHERE id = (
                SELECT t.id FROM tasks t
                WHERE t.status = 'queued' AND t.plugin = ?
                AND (t.depends_on_task_id IS NULL
                     OR EXISTS (SELECT 1 FROM tasks dep WHERE dep.id = t.depends_on_task_id AND dep.status = 'completed'))
                ORDER BY t.created_at ASC
                LIMIT 1
            )
            RETURNING *
            """,
            (worker_id, now, now, plugin),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                await self._db.commit()
                return self._row_to_task(row)
        return None

    async def update_task(self, task_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [task_id]
        await self._db.execute(
            f"UPDATE tasks SET {set_clause} WHERE id=?", values
        )
        await self._db.commit()

    async def get_tasks_by_ref_id(
        self, job_id: str, ref_id: str
    ) -> list[TaskRecord]:
        async with self._db.execute(
            "SELECT * FROM tasks WHERE job_id=? AND ref_id=? ORDER BY created_at ASC",
            (job_id, ref_id),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def get_stale_tasks(
        self, timeout_seconds: int = 120
    ) -> list[TaskRecord]:
        """Find running tasks with heartbeat older than timeout_seconds."""
        cutoff = (
            datetime.utcnow() - timedelta(seconds=timeout_seconds)
        ).isoformat()
        async with self._db.execute(
            "SELECT * FROM tasks WHERE status='running' AND heartbeat_at < ?",
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    # -------------------------------------------------------------------
    # Artifacts
    # -------------------------------------------------------------------

    async def insert_artifact(self, artifact: ArtifactRecord) -> None:
        await self._db.execute(
            """INSERT INTO artifacts (id, job_id, task_id, plugin, kind, filepath,
               original_filename, sha256, file_size_bytes, is_duplicate,
               metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact.id,
                artifact.job_id,
                artifact.task_id,
                artifact.plugin,
                artifact.kind,
                artifact.filepath,
                artifact.original_filename,
                artifact.sha256,
                artifact.file_size_bytes,
                artifact.is_duplicate,
                artifact.metadata_json,
                artifact.created_at,
            ),
        )
        await self._db.commit()

    async def get_artifacts(
        self,
        job_id: str | None = None,
        task_id: str | None = None,
        kind: str | None = None,
    ) -> list[ArtifactRecord]:
        conditions = []
        params = []
        if job_id is not None:
            conditions.append("job_id=?")
            params.append(job_id)
        if task_id is not None:
            conditions.append("task_id=?")
            params.append(task_id)
        if kind is not None:
            conditions.append("kind=?")
            params.append(kind)

        where = " AND ".join(conditions) if conditions else "1=1"
        async with self._db.execute(
            f"SELECT * FROM artifacts WHERE {where} ORDER BY created_at ASC",
            params,
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_artifact(row) for row in rows]

    async def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        async with self._db.execute(
            "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_artifact(row)
        return None

    async def find_duplicate(
        self, job_id: str, sha256: str
    ) -> ArtifactRecord | None:
        async with self._db.execute(
            "SELECT * FROM artifacts WHERE job_id=? AND sha256=? LIMIT 1",
            (job_id, sha256),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_artifact(row)
        return None

    # -------------------------------------------------------------------
    # Workers
    # -------------------------------------------------------------------

    async def upsert_worker(self, worker: WorkerRecord) -> None:
        await self._db.execute(
            """INSERT INTO workers (worker_id, hostname, plugin, capabilities_json,
               last_seen_at, registered_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(worker_id) DO UPDATE SET
                   hostname=excluded.hostname,
                   plugin=excluded.plugin,
                   capabilities_json=excluded.capabilities_json,
                   last_seen_at=excluded.last_seen_at,
                   registered_at=excluded.registered_at""",
            (
                worker.worker_id,
                worker.hostname,
                worker.plugin,
                worker.capabilities_json,
                worker.last_seen_at,
                worker.registered_at,
            ),
        )
        await self._db.commit()

    async def get_workers(self) -> list[WorkerRecord]:
        async with self._db.execute(
            "SELECT * FROM workers ORDER BY registered_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_worker(row) for row in rows]

    async def update_worker_heartbeat(self, worker_id: str) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "UPDATE workers SET last_seen_at=? WHERE worker_id=?",
            (now, worker_id),
        )
        await self._db.commit()

    # -------------------------------------------------------------------
    # Row conversion helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _row_to_task(row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            job_id=row["job_id"],
            plugin=row["plugin"],
            task_type=row["task_type"],
            payload_json=row["payload_json"],
            status=row["status"],
            depends_on_task_id=row["depends_on_task_id"],
            ref_id=row["ref_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            last_error=row["last_error"],
            assigned_worker_id=row["assigned_worker_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            heartbeat_at=row["heartbeat_at"],
        )

    @staticmethod
    def _row_to_job(row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            project_name=row["project_name"],
            spec_json=row["spec_json"],
            status=row["status"],
            total_tasks=row["total_tasks"],
            completed_tasks=row["completed_tasks"],
            failed_tasks=row["failed_tasks"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_artifact(row) -> ArtifactRecord:
        return ArtifactRecord(
            id=row["id"],
            job_id=row["job_id"],
            task_id=row["task_id"],
            plugin=row["plugin"],
            kind=row["kind"],
            filepath=row["filepath"],
            original_filename=row["original_filename"],
            sha256=row["sha256"],
            file_size_bytes=row["file_size_bytes"],
            is_duplicate=bool(row["is_duplicate"]),
            metadata_json=row["metadata_json"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_worker(row) -> WorkerRecord:
        return WorkerRecord(
            worker_id=row["worker_id"],
            hostname=row["hostname"],
            plugin=row["plugin"],
            capabilities_json=row["capabilities_json"],
            last_seen_at=row["last_seen_at"],
            registered_at=row["registered_at"],
        )
