# noapi Core Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-minded v1 of noapi — a generic, queue-based browser automation service with remote workers, plugin architecture, artifact storage, and a dashboard.

**Architecture:** FastAPI server with SQLite on VPS serves API + static SPA dashboard. Remote Playwright workers poll for tasks, execute plugin-defined browser flows, upload artifacts back. All site-specific logic lives in plugins that follow a standard interface. Pipeline support for chaining task outputs.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, Pydantic v2, Playwright (Python), httpx, uvicorn, python-multipart

---

## Phase 1: Foundation (Tasks 1-4)

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/services/__init__.py`
- Create: `app/workers/__init__.py`
- Create: `app/qc/__init__.py`
- Create: `app/cli/__init__.py`
- Create: `app/static/` (empty dir placeholder)
- Create: `plugins/__init__.py`
- Create: `plugins/_example/__init__.py`
- Create: `.gitignore`

**Step 1: Initialize git repo**

```bash
cd /Users/jacob/Projects/noapi
git init
```

**Step 2: Create requirements.txt**

```
fastapi>=0.115,<1.0
uvicorn>=0.34,<1.0
aiosqlite>=0.21,<1.0
pydantic>=2.10,<3.0
python-multipart>=0.0.20,<1.0
httpx>=0.28,<1.0
playwright>=1.50,<2.0
```

**Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
data/
sessions/
*.sqlite
*.db
.env
```

**Step 4: Create all empty `__init__.py` files and directory structure**

Create these directories and empty `__init__.py` files:
- `app/__init__.py`
- `app/services/__init__.py`
- `app/workers/__init__.py`
- `app/qc/__init__.py`
- `app/cli/__init__.py`
- `plugins/__init__.py`
- `plugins/_example/__init__.py`
- `examples/` (directory only)
- `tests/__init__.py`

**Step 5: Create virtual environment and install deps**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

**Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold project structure and dependencies"
```

---

### Task 2: Settings Module

**Files:**
- Create: `app/settings.py`

**Step 1: Create settings.py**

Settings loaded from environment variables with sensible defaults. Use `pydantic_settings` or plain os.environ. Keep it simple — just read env vars into a module-level object.

```python
"""Environment-based configuration for noapi."""

import os
from pathlib import Path


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        self.host: str = os.getenv("NOAPI_HOST", "0.0.0.0")
        self.port: int = int(os.getenv("NOAPI_PORT", "8000"))
        self.data_dir: Path = Path(os.getenv("NOAPI_DATA_DIR", "./data"))
        self.worker_key: str = os.getenv("NOAPI_WORKER_KEY", "")
        self.basic_auth: str = os.getenv("NOAPI_BASIC_AUTH", "")  # "user:password" or ""
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.getenv("NOAPI_CORS_ORIGINS", "").split(",")
            if o.strip()
        ]
        self.log_level: str = os.getenv("NOAPI_LOG_LEVEL", "INFO")
        self.root_path: str = os.getenv("NOAPI_ROOT_PATH", "")
        self.base_url: str = os.getenv("NOAPI_BASE_URL", "http://localhost:8000")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "queue.sqlite"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def ensure_dirs(self):
        """Create required data directories."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
```

**Step 2: Verify syntax**

```bash
python -c "from app.settings import settings; print(settings.data_dir)"
```

**Step 3: Commit**

```bash
git add app/settings.py
git commit -m "feat: add settings module with env-based configuration"
```

---

### Task 3: Pydantic Schemas

**Files:**
- Create: `app/schemas.py`

This is the central schema file. It defines:
1. Plugin base classes (`SiteFlowBase`, `FlowResult`, `NeedsHumanError`, `FlowError`, `HealthCheckResult`)
2. Job spec models (`TaskSpec`, `VariantExpansion`, `PipelineStep`, `JobSpec`)
3. Database record models (`TaskRecord`, `ArtifactRecord`, `JobRecord`, `WorkerRecord`)
4. API request/response models

**Step 1: Create schemas.py with all models**

Key models (implement all of these):

```python
# --- Plugin base classes ---

class FlowResult:
    """Result from a plugin flow execution."""
    success: bool
    artifact_paths: list[str]
    metadata: dict
    screenshots: list[str]

class NeedsHumanError(Exception):
    """Raised when human intervention is required."""
    def __init__(self, message: str, screenshot_path: str | None = None): ...

class FlowError(Exception):
    """Raised when flow fails but is retryable."""
    def __init__(self, message: str, screenshot_path: str | None = None): ...

class HealthCheckResult:
    """Result from plugin health check."""
    healthy: bool
    selectors_found: list[str]
    selectors_missing: list[str]
    message: str

# SiteFlowBase - ABC with execute(), detect_auth_required(), health_check()

# --- Job spec models (Pydantic) ---

class TaskSpec(BaseModel):
    plugin: str
    task_type: str
    params: dict[str, Any]
    depends_on: str | None = None
    ref_id: str | None = None

class VariantExpansion(BaseModel):
    plugin: str
    task_type: str
    param_template: dict[str, Any]
    expand_over: dict[str, list[Any]]
    variants: int = 1
    depends_on: str | None = None
    ref_id: str | None = None

class PipelineStep(BaseModel):
    source_ref: str
    plugin: str
    task_type: str
    param_template: dict[str, Any]
    outputs_per_input: int = 1
    trigger_mode: str = "each"  # "each" or "all"

class JobSpec(BaseModel):
    project_name: str
    description: str | None = None
    tasks: list[TaskSpec] = []
    expansions: list[VariantExpansion] = []
    pipelines: list[PipelineStep] = []
    global_params: dict[str, Any] = {}
    naming_prefix: str | None = None

# --- DB record models ---

class TaskRecord(BaseModel):
    id: str
    job_id: str
    plugin: str
    task_type: str
    payload_json: str
    status: str = "queued"
    depends_on_task_id: str | None = None
    ref_id: str | None = None  # Carried from TaskSpec for pipeline matching
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
    assigned_worker_id: str | None = None
    created_at: str
    updated_at: str
    heartbeat_at: str | None = None

class ArtifactRecord(BaseModel):
    id: str
    job_id: str
    task_id: str
    plugin: str
    kind: str
    filepath: str
    original_filename: str | None = None
    sha256: str | None = None
    file_size_bytes: int | None = None
    is_duplicate: bool = False
    metadata_json: str | None = None
    created_at: str

class JobRecord(BaseModel):
    id: str
    project_name: str | None = None
    spec_json: str
    status: str = "active"
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    created_at: str
    updated_at: str

class WorkerRecord(BaseModel):
    worker_id: str
    hostname: str | None = None
    plugin: str | None = None
    capabilities_json: str | None = None
    last_seen_at: str | None = None
    registered_at: str

# --- API request/response models ---
# ClaimRequest, HeartbeatRequest, CompleteRequest, FailRequest,
# WorkerRegisterRequest, JobSummary, TaskSummary, etc.
```

Important: The `tasks` table schema needs a `ref_id` column (not in the original SQL but needed for pipeline matching). Add it.

**Step 2: Verify syntax**

```bash
python -c "from app.schemas import JobSpec, TaskRecord; print('OK')"
```

**Step 3: Commit**

```bash
git add app/schemas.py
git commit -m "feat: add Pydantic schemas for jobs, tasks, artifacts, workers, and plugin base classes"
```

---

### Task 4: Database Layer

**Files:**
- Create: `app/db.py`
- Create: `tests/test_db.py`

**Step 1: Write tests for DB operations**

Test the key operations:
- `init_db()` creates tables
- `insert_task()` and `get_task()` round-trip
- `claim_task()` atomically claims a queued task (returns None when none available)
- `update_task_status()` transitions correctly
- `insert_artifact()` and `get_artifacts()` round-trip
- `insert_job()` and `get_job()` round-trip

Use an in-memory SQLite database for tests (`":memory:"`).

```python
import pytest
import pytest_asyncio
from app.db import Database

@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.init()
    yield database
    await database.close()

@pytest.mark.asyncio
async def test_init_creates_tables(db):
    # Verify tables exist by querying sqlite_master
    ...

@pytest.mark.asyncio
async def test_insert_and_get_task(db):
    ...

@pytest.mark.asyncio
async def test_claim_task_atomic(db):
    # Insert a queued task, claim it, verify status changes
    # Claim again with different worker, verify returns None
    ...

@pytest.mark.asyncio
async def test_claim_skips_blocked_dependencies(db):
    # Task B depends on Task A (not completed). Claiming should skip B.
    ...
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db.py -v
```
Expected: ImportError — `app.db` doesn't exist yet.

**Step 3: Implement db.py**

The `Database` class wraps aiosqlite with these methods:

```python
class Database:
    def __init__(self, db_path: str | Path): ...
    async def init(self): ...           # CREATE TABLE IF NOT EXISTS for all 4 tables + indexes
    async def close(self): ...

    # Jobs
    async def insert_job(self, job: JobRecord) -> None: ...
    async def get_job(self, job_id: str) -> JobRecord | None: ...
    async def get_jobs(self) -> list[JobRecord]: ...
    async def update_job(self, job_id: str, **fields) -> None: ...
    async def update_job_counts(self, job_id: str) -> None:
        """Recount tasks by status and update job record."""

    # Tasks
    async def insert_task(self, task: TaskRecord) -> None: ...
    async def get_task(self, task_id: str) -> TaskRecord | None: ...
    async def get_tasks(self, job_id: str | None = None, status: str | None = None,
                        plugin: str | None = None) -> list[TaskRecord]: ...
    async def claim_task(self, worker_id: str, plugin: str) -> TaskRecord | None:
        """Atomically claim a queued task. Only claims tasks whose dependencies are met."""
    async def update_task(self, task_id: str, **fields) -> None: ...
    async def get_tasks_by_ref_id(self, job_id: str, ref_id: str) -> list[TaskRecord]: ...
    async def get_stale_tasks(self, timeout_seconds: int = 120) -> list[TaskRecord]: ...

    # Artifacts
    async def insert_artifact(self, artifact: ArtifactRecord) -> None: ...
    async def get_artifacts(self, job_id: str | None = None, task_id: str | None = None,
                           kind: str | None = None) -> list[ArtifactRecord]: ...
    async def get_artifact(self, artifact_id: str) -> ArtifactRecord | None: ...
    async def find_duplicate(self, job_id: str, sha256: str) -> ArtifactRecord | None: ...

    # Workers
    async def upsert_worker(self, worker: WorkerRecord) -> None: ...
    async def get_workers(self) -> list[WorkerRecord]: ...
    async def update_worker_heartbeat(self, worker_id: str) -> None: ...
```

SQL schema includes the `ref_id TEXT` column on tasks (for pipeline matching):

```sql
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
```

The `claim_task` query is critical — it must atomically select and update:

```sql
UPDATE tasks SET status='running', assigned_worker_id=?, heartbeat_at=?, updated_at=?
WHERE id = (
    SELECT t.id FROM tasks t
    WHERE t.status = 'queued' AND t.plugin = ?
    AND (t.depends_on_task_id IS NULL
         OR EXISTS (SELECT 1 FROM tasks dep WHERE dep.id = t.depends_on_task_id AND dep.status = 'completed'))
    ORDER BY t.created_at ASC
    LIMIT 1
)
RETURNING *;
```

Note: SQLite supports `RETURNING` since 3.35. If the environment doesn't support it, use a two-step approach within a transaction.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```

**Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add database layer with async SQLite operations"
```

---

## Phase 2: Core Services (Tasks 5-8)

### Task 5: Plugin Registry

**Files:**
- Create: `app/plugin_registry.py`

**Step 1: Create plugin_registry.py**

In-memory registry that stores plugin manifests. Workers upload manifests on registration. The server uses them to validate job specs.

```python
class PluginRegistry:
    """In-memory registry of plugin manifests uploaded by workers."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}  # name -> manifest dict

    def register(self, manifest: dict) -> None:
        """Register or update a plugin manifest."""
        name = manifest["name"]
        self._plugins[name] = manifest

    def get(self, name: str) -> dict | None: ...
    def list_all(self) -> list[dict]: ...
    def has_plugin(self, name: str) -> bool: ...

    def get_task_type(self, plugin: str, task_type: str) -> dict | None:
        """Get a specific task type definition from a plugin manifest."""
        ...

    def validate_task(self, plugin: str, task_type: str, params: dict) -> list[str]:
        """
        Validate a task against its plugin manifest.
        Returns list of error messages (empty if valid).
        Checks: plugin exists, task_type exists, required params present,
        enum values valid.
        """
        ...
```

**Step 2: Verify syntax**

```bash
python -c "from app.plugin_registry import PluginRegistry; print('OK')"
```

**Step 3: Commit**

```bash
git add app/plugin_registry.py
git commit -m "feat: add in-memory plugin manifest registry"
```

---

### Task 6: Scheduler

**Files:**
- Create: `app/services/scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write tests for scheduler**

Test:
- `schedule_job()` with explicit `TaskSpec` items creates correct tasks
- `schedule_job()` with `VariantExpansion` creates cartesian product * variants tasks
- `schedule_job()` with dependencies sets `depends_on_task_id` and initial status correctly
- `schedule_job()` rejects unknown plugin/task_type
- `schedule_job()` merges `global_params` into task params
- Pipeline steps are stored on the job but don't create tasks at submission time

```python
@pytest.mark.asyncio
async def test_schedule_explicit_tasks(db):
    registry = PluginRegistry()
    registry.register(MOCK_MANIFEST)
    scheduler = Scheduler(db, registry)
    job_spec = JobSpec(project_name="test", tasks=[
        TaskSpec(plugin="example", task_type="generate_image", params={"prompt": "hello"})
    ])
    job = await scheduler.schedule_job(job_spec)
    tasks = await db.get_tasks(job_id=job.id)
    assert len(tasks) == 1
    assert tasks[0].status == "queued"

@pytest.mark.asyncio
async def test_variant_expansion_cartesian(db):
    # expand_over={"a": [1,2], "b": [3,4]}, variants=2 -> 2*2*2 = 8 tasks
    ...

@pytest.mark.asyncio
async def test_rejects_unknown_plugin(db):
    # Should raise ValueError with clear message
    ...
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scheduler.py -v
```

**Step 3: Implement scheduler.py**

```python
class Scheduler:
    def __init__(self, db: Database, registry: PluginRegistry): ...

    async def schedule_job(self, spec: JobSpec) -> JobRecord:
        """
        Parse job spec, validate against registry, create job + tasks in DB.
        Returns the created JobRecord.
        """
        # 1. Validate all plugin/task_type references
        # 2. Create JobRecord
        # 3. Process spec.tasks -> create TaskRecord for each
        # 4. Process spec.expansions -> cartesian product, create TaskRecords
        # 5. For dependencies (depends_on ref_id): resolve ref_id -> task IDs,
        #    set depends_on_task_id. If expansion, first task in the ref group.
        #    Set status='blocked' for tasks with unmet dependencies.
        # 6. Store pipeline steps in job spec (processed at completion time)
        # 7. Update job.total_tasks count
        ...
```

For variant expansion, compute cartesian product of `expand_over` values:

```python
import itertools

def expand_variants(expansion: VariantExpansion, global_params: dict) -> list[dict]:
    """Return list of param dicts from cartesian product * variants."""
    keys = list(expansion.expand_over.keys())
    values = list(expansion.expand_over.values())
    result = []
    for combo in itertools.product(*values):
        params = {**global_params, **expansion.param_template}
        for key, val in zip(keys, combo):
            # Replace {variable} placeholders in string values
            for pk, pv in params.items():
                if isinstance(pv, str) and f"{{{key}}}" in pv:
                    params[pk] = pv.replace(f"{{{key}}}", str(val))
                elif pk == key:
                    params[pk] = val
        for _ in range(expansion.variants):
            result.append(dict(params))
    return result
```

**Step 4: Run tests**

```bash
pytest tests/test_scheduler.py -v
```

**Step 5: Commit**

```bash
git add app/services/scheduler.py tests/test_scheduler.py
git commit -m "feat: add scheduler for job spec parsing and task creation"
```

---

### Task 7: Pipeline Resolution

**Files:**
- Create: `app/services/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write tests for pipeline**

Test:
- `trigger_mode="each"`: completing one task creates one downstream task with `{artifact_path}` resolved
- `trigger_mode="all"`: completing one task does nothing until all tasks with same ref_id complete, then creates downstream tasks with `{artifact_paths}` list
- `outputs_per_input`: creates N downstream tasks per trigger
- No pipeline steps: `check_pipelines()` is a no-op

```python
@pytest.mark.asyncio
async def test_each_mode_creates_on_completion(db):
    # Setup: job with pipeline step (trigger_mode="each", source_ref="img")
    # Complete a task with ref_id="img"
    # Verify downstream task created with {artifact_path} resolved
    ...

@pytest.mark.asyncio
async def test_all_mode_waits_for_all(db):
    # Setup: 2 tasks with ref_id="img", pipeline with trigger_mode="all"
    # Complete first task -> no downstream tasks yet
    # Complete second task -> downstream tasks created with {artifact_paths}
    ...
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline.py -v
```

**Step 3: Implement pipeline.py**

```python
class PipelineResolver:
    def __init__(self, db: Database): ...

    async def check_pipelines(self, completed_task: TaskRecord, job_record: JobRecord) -> list[TaskRecord]:
        """
        Called when a task completes. Checks if any pipeline steps should trigger.
        Returns list of newly created downstream tasks.
        """
        spec = JobSpec.model_validate_json(job_record.spec_json)
        created = []
        for step in spec.pipelines:
            if step.source_ref != completed_task.ref_id:
                continue
            if step.trigger_mode == "each":
                created.extend(await self._trigger_each(step, completed_task, job_record))
            elif step.trigger_mode == "all":
                created.extend(await self._trigger_all(step, completed_task, job_record))
        return created

    async def _trigger_each(self, step, completed_task, job_record) -> list[TaskRecord]:
        """Create downstream tasks for a single completed upstream task."""
        artifacts = await self.db.get_artifacts(task_id=completed_task.id)
        artifact_paths = [a.filepath for a in artifacts]
        # Resolve {artifact_path} in param_template
        # Create outputs_per_input tasks
        ...

    async def _trigger_all(self, step, completed_task, job_record) -> list[TaskRecord]:
        """Create downstream tasks only when ALL upstream tasks with matching ref_id are done."""
        all_ref_tasks = await self.db.get_tasks_by_ref_id(job_record.id, step.source_ref)
        if not all(t.status == "completed" for t in all_ref_tasks):
            return []
        # Gather all artifact paths from all completed tasks
        # Resolve {artifact_paths} as JSON list in param_template
        # Create outputs_per_input tasks
        ...
```

**Step 4: Run tests**

```bash
pytest tests/test_pipeline.py -v
```

**Step 5: Commit**

```bash
git add app/services/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline resolver with each/all trigger modes"
```

---

### Task 8: QC Module

**Files:**
- Create: `app/qc/basic.py`

**Step 1: Create basic.py**

```python
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
```

**Step 2: Verify syntax**

```bash
python -c "from app.qc.basic import compute_sha256; print('OK')"
```

**Step 3: Commit**

```bash
git add app/qc/basic.py
git commit -m "feat: add QC utilities for hashing, size checks, and artifact naming"
```

---

## Phase 3: API (Tasks 9-13)

### Task 9: FastAPI App Shell with Auth Middleware

**Files:**
- Create: `app/main.py`

**Step 1: Create main.py**

This is the FastAPI application with:
- Lifespan handler (init DB, start stale task checker)
- Auth middleware (worker key + optional basic auth)
- CORS middleware
- Static file mounting
- Router includes for all endpoint groups

```python
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import base64, secrets

from app.settings import settings
from app.db import Database
from app.plugin_registry import PluginRegistry

logger = logging.getLogger("noapi")

db = Database(settings.db_path)
registry = PluginRegistry()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await db.init()
    # Start stale task recovery loop
    task = asyncio.create_task(stale_task_loop())
    yield
    task.cancel()
    await db.close()

app = FastAPI(title="noapi", root_path=settings.root_path, lifespan=lifespan)

# --- Auth Middleware ---

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Worker endpoints: check X-Worker-Key
        if path.startswith("/api/workers") or path.startswith("/api/tasks/claim") or \
           path == "/api/upload" or (path.startswith("/api/tasks/") and request.method == "POST"):
            key = request.headers.get("X-Worker-Key", "")
            if settings.worker_key and not secrets.compare_digest(key, settings.worker_key):
                return Response("Unauthorized", status_code=401)
        # Dashboard + job API: optional basic auth
        elif settings.basic_auth:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return Response("Unauthorized", status_code=401,
                               headers={"WWW-Authenticate": "Basic"})
            try:
                decoded = base64.b64decode(auth[6:]).decode()
                if not secrets.compare_digest(decoded, settings.basic_auth):
                    return Response("Unauthorized", status_code=401)
            except Exception:
                return Response("Unauthorized", status_code=401)
        return await call_next(request)

app.add_middleware(AuthMiddleware)

# CORS
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])

# Static files (dashboard)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Stale task recovery
async def stale_task_loop():
    while True:
        await asyncio.sleep(60)
        try:
            stale = await db.get_stale_tasks(timeout_seconds=120)
            now = datetime.utcnow().isoformat()
            for task in stale:
                if task.attempts < task.max_attempts:
                    await db.update_task(task.id, status="queued",
                                        assigned_worker_id=None, heartbeat_at=None,
                                        updated_at=now)
                else:
                    await db.update_task(task.id, status="failed",
                                        last_error="Worker heartbeat timeout",
                                        updated_at=now)
                await db.update_job_counts(task.job_id)
        except Exception:
            logger.exception("Error in stale task recovery")

# Include routers (added in subsequent tasks)
# from app.routes import jobs, tasks, artifacts, workers, plugins, health
# app.include_router(jobs.router)
# ...
```

**Step 2: Verify syntax**

```bash
python -c "from app.main import app; print(app.title)"
```

**Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: add FastAPI app shell with auth middleware and stale task recovery"
```

---

### Task 10: API Routes — Health, Workers, Plugins

**Files:**
- Create: `app/routes/__init__.py`
- Create: `app/routes/health.py`
- Create: `app/routes/workers.py`
- Create: `app/routes/plugins.py`
- Modify: `app/main.py` (include routers)

**Step 1: Create health.py**

```python
# GET /api/health — DB connectivity, disk space
# GET /api/health/selectors?plugin={name} — placeholder for selector health check
```

**Step 2: Create workers.py**

```python
# POST /api/workers/register — Register worker, optionally register plugin manifest
#   Body: WorkerRegisterRequest { worker_id, hostname, plugin, capabilities, manifest_json }
#   On first registration with manifest_json: call registry.register(manifest)
#   Upsert worker in DB
```

**Step 3: Create plugins.py**

```python
# GET /api/plugins — List all registered manifests
# GET /api/plugins/{name} — Get specific manifest
```

**Step 4: Wire routers into main.py**

Add `app.include_router(...)` calls for each router with prefix `/api`.

**Step 5: Verify syntax**

```bash
python -c "from app.main import app; print([r.path for r in app.routes])"
```

**Step 6: Commit**

```bash
git add app/routes/ app/main.py
git commit -m "feat: add health, worker registration, and plugin API routes"
```

---

### Task 11: API Routes — Tasks (Claim, Heartbeat, Complete, Fail)

**Files:**
- Create: `app/routes/tasks.py`
- Modify: `app/main.py` (include router)

**Step 1: Create tasks.py**

Endpoints:
- `GET /api/tasks?job_id=&status=&plugin=` — List tasks with filters
- `POST /api/tasks/claim` — Atomically claim a queued task (worker endpoint)
- `POST /api/tasks/{task_id}/heartbeat` — Worker heartbeat
- `POST /api/tasks/{task_id}/complete` — Mark task completed, trigger pipeline check
- `POST /api/tasks/{task_id}/fail` — Mark task failed or needs_human
- `POST /api/tasks/{task_id}/retry` — Reset needs_human task to queued

The `complete` endpoint is critical — after marking the task completed:
1. Update job counts
2. Call `PipelineResolver.check_pipelines()` to create downstream tasks
3. Update job counts again if new tasks were created
4. Check if all tasks in job are done — if so, update job status

The `fail` endpoint handles retry logic:
- If `needs_human=true`: set status to `needs_human`
- Else if `attempts < max_attempts`: increment attempts, set status to `queued`, clear assigned_worker
- Else: set status to `failed`
- Always update job counts

**Step 2: Wire router into main.py**

**Step 3: Commit**

```bash
git add app/routes/tasks.py app/main.py
git commit -m "feat: add task claim, heartbeat, complete, and fail API routes"
```

---

### Task 12: API Routes — Artifacts + Upload

**Files:**
- Create: `app/routes/artifacts.py`
- Modify: `app/main.py` (include router, add artifact static mount)

**Step 1: Create artifacts.py**

Endpoints:
- `GET /api/artifacts?job_id=&task_id=&kind=` — List artifacts with filters
- `GET /api/artifacts/{artifact_id}/download` — Download artifact file (FileResponse)
- `POST /api/upload/{job_id}/{task_id}` — Multipart upload (worker endpoint)

Upload endpoint logic:
1. Receive uploaded files via `python-multipart`
2. Determine `kind` from file extension or query param
3. Save to `data/jobs/{job_id}/artifacts/{kind}/`
4. Compute sha256 via `qc.basic.compute_sha256()`
5. Check for duplicates via `db.find_duplicate()`
6. Generate deterministic filename via `qc.basic.generate_artifact_filename()`
7. Rename file to deterministic name
8. Write sidecar JSON with metadata
9. Insert artifact record in DB

**Step 2: Add static file mount for artifacts**

In `main.py`, mount `data/jobs/` so artifact files are serveable. Or use `FileResponse` in the download endpoint.

**Step 3: Commit**

```bash
git add app/routes/artifacts.py app/main.py
git commit -m "feat: add artifact listing, download, and upload routes"
```

---

### Task 13: API Routes — Jobs

**Files:**
- Create: `app/routes/jobs.py`
- Modify: `app/main.py` (include router)

**Step 1: Create jobs.py**

Endpoints:
- `POST /api/jobs` — Submit job spec (JSON body). Validate against registry, call scheduler.
- `GET /api/jobs` — List all jobs with summary counts
- `GET /api/jobs/{job_id}` — Job detail with task breakdown by status
- `POST /api/jobs/{job_id}/cancel` — Cancel all queued/blocked tasks in a job

The submit endpoint:
1. Parse `JobSpec` from request body
2. Call `scheduler.schedule_job(spec)` — this validates and creates tasks
3. Return the created job with task count

**Step 2: Wire router, serve dashboard index at `/`**

Add a catch-all route or mount that serves `index.html` at `/`.

**Step 3: Commit**

```bash
git add app/routes/jobs.py app/main.py
git commit -m "feat: add job submission, listing, and cancellation routes"
```

---

## Phase 4: Worker (Tasks 14-16)

### Task 14: Browser Helpers

**Files:**
- Create: `app/workers/browser.py`

**Step 1: Create browser.py**

Playwright helper functions for workers:

```python
from playwright.async_api import async_playwright, BrowserContext, Page
from pathlib import Path
import os

WORKER_SESSION_ROOT = Path(os.getenv("WORKER_SESSION_ROOT", "./sessions"))

async def create_persistent_context(
    plugin_name: str,
    headed: bool = True,
) -> tuple[BrowserContext, "Playwright"]:
    """
    Create a Playwright persistent browser context.
    Session data stored in WORKER_SESSION_ROOT/{plugin_name}/
    Returns (context, playwright_instance) — caller must close both.
    """
    session_dir = WORKER_SESSION_ROOT / plugin_name
    session_dir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(session_dir),
        headless=not headed,
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    return context, pw

async def screenshot_on_error(page: Page, task_id: str, screenshot_dir: str) -> str:
    """Take a screenshot and return the file path."""
    path = Path(screenshot_dir) / f"{task_id}_error.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(path), full_page=True)
    return str(path)

async def wait_with_timeout(page: Page, selector: str, timeout_ms: int = 30000) -> None:
    """Wait for selector with a clear error message on timeout."""
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
    except Exception:
        raise TimeoutError(f"Selector '{selector}' not found within {timeout_ms}ms")

async def download_artifact(page: Page, download_trigger, download_dir: str) -> str:
    """
    Execute a download trigger action and wait for the download.
    Returns the path to the downloaded file.
    """
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    async with page.expect_download() as download_info:
        await download_trigger()
    download = await download_info.value
    dest = download_path / download.suggested_filename
    await download.save_as(str(dest))
    return str(dest)
```

**Step 2: Verify syntax**

```bash
python -c "from app.workers.browser import create_persistent_context; print('OK')"
```

**Step 3: Commit**

```bash
git add app/workers/browser.py
git commit -m "feat: add Playwright browser helpers for workers"
```

---

### Task 15: Remote Worker

**Files:**
- Create: `app/workers/remote_worker.py`

**Step 1: Create remote_worker.py**

The remote worker loop that:
1. Registers with VPS (includes plugin manifest)
2. Polls for tasks
3. Executes plugin flows
4. Uploads artifacts
5. Reports results
6. Sends heartbeats

```python
import asyncio
import json
import logging
import importlib
from pathlib import Path
import httpx

logger = logging.getLogger("noapi.worker")

class RemoteWorker:
    def __init__(
        self,
        server_url: str,
        plugin_name: str,
        worker_id: str,
        worker_key: str = "",
        headed: bool = True,
        poll_interval: float = 5.0,
    ):
        self.server_url = server_url.rstrip("/")
        self.plugin_name = plugin_name
        self.worker_id = worker_id
        self.worker_key = worker_key
        self.headed = headed
        self.poll_interval = poll_interval
        self.flow = None
        self._running = False
        self._heartbeat_task = None

    def _headers(self) -> dict:
        return {"X-Worker-Key": self.worker_key}

    def _load_plugin(self):
        """Import and instantiate the plugin flow class."""
        module = importlib.import_module(f"plugins.{self.plugin_name}.flows")
        # Find the SiteFlowBase subclass
        from app.schemas import SiteFlowBase
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, SiteFlowBase) and attr is not SiteFlowBase:
                self.flow = attr()
                return
        raise RuntimeError(f"No SiteFlowBase subclass found in plugins.{self.plugin_name}.flows")

    def _load_manifest(self) -> dict:
        """Load plugin manifest.json."""
        manifest_path = Path(f"plugins/{self.plugin_name}/manifest.json")
        with open(manifest_path) as f:
            return json.load(f)

    async def register(self, client: httpx.AsyncClient):
        """Register with the VPS server."""
        manifest = self._load_manifest()
        import socket
        resp = await client.post(f"{self.server_url}/api/workers/register", json={
            "worker_id": self.worker_id,
            "hostname": socket.gethostname(),
            "plugin": self.plugin_name,
            "capabilities": {"headed": self.headed},
            "manifest_json": manifest,
        }, headers=self._headers())
        resp.raise_for_status()
        logger.info("Registered with server as %s", self.worker_id)

    async def claim_task(self, client: httpx.AsyncClient) -> dict | None:
        """Try to claim a task from the server."""
        resp = await client.post(f"{self.server_url}/api/tasks/claim", json={
            "worker_id": self.worker_id,
            "plugin": self.plugin_name,
        }, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("task")

    async def heartbeat_loop(self, client: httpx.AsyncClient, task_id: str):
        """Send heartbeats every 30 seconds."""
        while True:
            await asyncio.sleep(30)
            try:
                await client.post(
                    f"{self.server_url}/api/tasks/{task_id}/heartbeat",
                    json={"worker_id": self.worker_id},
                    headers=self._headers(),
                )
            except Exception:
                logger.warning("Heartbeat failed for task %s", task_id)

    async def upload_artifacts(self, client: httpx.AsyncClient, job_id: str, task_id: str,
                                artifact_paths: list[str]):
        """Upload artifact files to the server."""
        for path in artifact_paths:
            p = Path(path)
            if not p.exists():
                continue
            with open(p, "rb") as f:
                files = {"file": (p.name, f)}
                resp = await client.post(
                    f"{self.server_url}/api/upload/{job_id}/{task_id}",
                    files=files,
                    headers=self._headers(),
                )
                resp.raise_for_status()

    async def run(self):
        """Main worker loop."""
        self._load_plugin()
        self._running = True
        from app.workers.browser import create_persistent_context, screenshot_on_error

        async with httpx.AsyncClient(timeout=60) as client:
            await self.register(client)
            context, pw = await create_persistent_context(self.plugin_name, self.headed)

            try:
                page = await context.new_page()
                while self._running:
                    task_data = await self.claim_task(client)
                    if not task_data:
                        await asyncio.sleep(self.poll_interval)
                        continue

                    task_id = task_data["id"]
                    job_id = task_data["job_id"]
                    payload = json.loads(task_data["payload_json"])
                    download_dir = f"./downloads/{job_id}/{task_id}"
                    screenshot_dir = f"./screenshots/{job_id}"
                    Path(download_dir).mkdir(parents=True, exist_ok=True)
                    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)

                    logger.info("Claimed task %s (type=%s)", task_id, task_data["task_type"])

                    # Start heartbeat
                    hb_task = asyncio.create_task(self.heartbeat_loop(client, task_id))

                    try:
                        # Check auth
                        if await self.flow.detect_auth_required(page):
                            ss = await screenshot_on_error(page, task_id, screenshot_dir)
                            raise NeedsHumanError("Authentication required", ss)

                        result = await self.flow.execute(page, payload, download_dir)

                        # Upload artifacts
                        if result.artifact_paths:
                            await self.upload_artifacts(client, job_id, task_id, result.artifact_paths)
                        # Upload screenshots
                        if result.screenshots:
                            await self.upload_artifacts(client, job_id, task_id, result.screenshots)

                        # Report completion
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/complete",
                            json={"worker_id": self.worker_id, "result_json": result.metadata},
                            headers=self._headers(),
                        )
                        logger.info("Completed task %s", task_id)

                    except NeedsHumanError as e:
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/fail",
                            json={"worker_id": self.worker_id, "error": e.message,
                                  "needs_human": True, "screenshot_path": e.screenshot_path},
                            headers=self._headers(),
                        )
                    except Exception as e:
                        ss = await screenshot_on_error(page, task_id, screenshot_dir)
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/fail",
                            json={"worker_id": self.worker_id, "error": str(e),
                                  "needs_human": False, "screenshot_path": ss},
                            headers=self._headers(),
                        )
                    finally:
                        hb_task.cancel()

            finally:
                await context.close()
                await pw.stop()

    def stop(self):
        self._running = False
```

**Step 2: Verify syntax**

```bash
python -c "from app.workers.remote_worker import RemoteWorker; print('OK')"
```

**Step 3: Commit**

```bash
git add app/workers/remote_worker.py
git commit -m "feat: add remote worker with poll/claim/execute/upload loop"
```

---

### Task 16: CLI Entry Points

**Files:**
- Create: `app/cli/server.py`
- Create: `app/cli/worker.py`
- Create: `app/cli/auth.py`

**Step 1: Create server.py**

```python
"""Start the noapi server: python -m app.cli.server"""
import uvicorn
import logging
from app.settings import settings

def main():
    logging.basicConfig(level=getattr(logging, settings.log_level),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                log_level=settings.log_level.lower())

if __name__ == "__main__":
    main()
```

**Step 2: Create worker.py**

```python
"""Start a noapi worker: python -m app.cli.worker --server URL --plugin NAME --worker-id ID"""
import argparse
import asyncio
import logging
import os

def main():
    parser = argparse.ArgumentParser(description="noapi worker")
    parser.add_argument("--server", required=True, help="VPS server URL")
    parser.add_argument("--plugin", required=True, help="Plugin name to load")
    parser.add_argument("--worker-id", required=True, help="Unique worker identifier")
    parser.add_argument("--headed", action="store_true", default=True, help="Run browser headed")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Poll interval in seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from app.workers.remote_worker import RemoteWorker
    worker = RemoteWorker(
        server_url=args.server,
        plugin_name=args.plugin,
        worker_id=args.worker_id,
        worker_key=os.getenv("NOAPI_WORKER_KEY", ""),
        headed=not args.headless,
        poll_interval=args.poll_interval,
    )

    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        worker.stop()

if __name__ == "__main__":
    main()
```

**Step 3: Create auth.py**

```python
"""Auth helper: python -m app.cli.auth --plugin NAME"""
import argparse
import asyncio

async def run_auth(plugin_name: str):
    from app.workers.browser import create_persistent_context
    import json
    from pathlib import Path

    manifest_path = Path(f"plugins/{plugin_name}/manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    auth_url = manifest.get("auth_url", "")
    print(f"Opening browser for manual login to: {auth_url}")
    print("Log in manually, then close the browser or press Ctrl+C.")

    context, pw = await create_persistent_context(plugin_name, headed=True)
    page = await context.new_page()
    if auth_url:
        await page.goto(auth_url)

    try:
        # Wait until user closes the browser
        await page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    finally:
        await context.close()
        await pw.stop()
    print("Session saved.")

def main():
    parser = argparse.ArgumentParser(description="noapi auth helper")
    parser.add_argument("--plugin", required=True, help="Plugin name")
    args = parser.parse_args()
    asyncio.run(run_auth(args.plugin))

if __name__ == "__main__":
    main()
```

**Step 4: Verify syntax for all three**

```bash
python -c "import app.cli.server" && python -c "import app.cli.worker" && python -c "import app.cli.auth"
```

**Step 5: Commit**

```bash
git add app/cli/
git commit -m "feat: add CLI entry points for server, worker, and auth helper"
```

---

## Phase 5: Dashboard (Tasks 17-19)

### Task 17: Dashboard HTML

**Files:**
- Create: `app/static/index.html`

**Step 1: Create index.html**

Single-page application with:
- Tab navigation: Jobs | Workers | Plugins
- Jobs tab: upload form for job spec JSON + jobs list table + job detail drill-down
- Job detail: task table grouped by status, "Needs Human" section with screenshots, artifacts grid
- Workers tab: worker table with status, plugin, last seen
- Plugins tab: plugin cards with capabilities
- Uses `/static/app.js` and `/static/styles.css`

The HTML should be clean, semantic, and functional. No framework. The `<main>` has 3 tab content divs. Navigation uses `<nav>` with hash links.

**Step 2: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add dashboard HTML structure"
```

---

### Task 18: Dashboard CSS

**Files:**
- Create: `app/static/styles.css`

**Step 1: Create styles.css**

Clean, functional styling:
- Dark theme (professional, easy on eyes for monitoring)
- Responsive layout
- Status badges with colors (queued=gray, running=blue, completed=green, failed=red, needs_human=orange, blocked=purple)
- Progress bars for job completion
- Grid layout for artifact previews
- Table styling for task lists

**Step 2: Commit**

```bash
git add app/static/styles.css
git commit -m "feat: add dashboard styles with dark theme"
```

---

### Task 19: Dashboard JavaScript

**Files:**
- Create: `app/static/app.js`

**Step 1: Create app.js**

Vanilla JS SPA with:

```javascript
// State
let currentTab = 'jobs';
let currentJobId = null;
let pollInterval = null;

// Tab switching
function switchTab(tab) { ... }
window.addEventListener('hashchange', () => switchTab(location.hash.slice(1) || 'jobs'));

// Polling (every 3 seconds)
function startPolling() {
    pollInterval = setInterval(async () => {
        await refreshJobs();
        await refreshWorkers();
        if (currentJobId) await refreshJobDetail(currentJobId);
    }, 3000);
}

// API helpers
async function api(path, options = {}) {
    const resp = await fetch(`/api${path}`, options);
    return resp.json();
}

// Jobs tab
async function refreshJobs() { ... }
async function uploadJobSpec(file) { ... }
async function showJobDetail(jobId) { ... }
async function refreshJobDetail(jobId) { ... }
async function cancelJob(jobId) { ... }
async function retryTask(taskId) { ... }

// Workers tab
async function refreshWorkers() { ... }

// Plugins tab
async function refreshPlugins() { ... }

// Artifact rendering
function renderArtifact(artifact) {
    // Image: <img> with lazy loading
    // Video: <video> with controls
    // Other: download link
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    switchTab(location.hash.slice(1) || 'jobs');
    startPolling();
});
```

Key UI behaviors:
- Job spec upload: file input + drag-and-drop, sends `POST /api/jobs` with JSON body
- Job list: clickable rows that drill into detail view
- Task table in detail view: sortable by status, shows worker assignment
- Needs Human section: prominently displayed at top of job detail with orange styling, shows screenshot thumbnails and error messages
- Retry button on needs_human tasks: calls `POST /api/tasks/{id}/retry`
- Artifact grid: lazy-loaded image thumbnails, click to open full size
- Workers table: shows "online"/"stale" based on last_seen vs. 2-minute threshold

**Step 2: Verify JS syntax**

```bash
node --check app/static/app.js
```

**Step 3: Commit**

```bash
git add app/static/app.js
git commit -m "feat: add dashboard JavaScript with polling and SPA routing"
```

---

## Phase 6: Example Plugin & Docs (Tasks 20-23)

### Task 20: Example Plugin Template

**Files:**
- Create: `plugins/_example/manifest.json`
- Create: `plugins/_example/selectors.py`
- Create: `plugins/_example/flows.py`
- Create: `plugins/_example/errors.py`
- Create: `plugins/_example/README.md`

**Step 1: Create manifest.json**

Well-commented example with two task types:
- `generate_image`: text prompt -> image artifact
- `upscale_image`: image input -> higher-res image artifact

Include full params_schema with required/optional/enum/default fields demonstrated.

**Step 2: Create selectors.py**

Organized by flow step with comments explaining the pattern:
```python
# Login detection
LOGIN_FORM = "form#login"
LOGIN_BUTTON = "button[type=submit]"

# Image generation flow
PROMPT_INPUT = "textarea#prompt"
GENERATE_BUTTON = "button#generate"
PROGRESS_BAR = ".progress-bar"
RESULT_IMAGE = "img.result"
DOWNLOAD_BUTTON = "a.download"
```

**Step 3: Create flows.py**

Skeleton `SiteFlowBase` implementation with:
- Auth detection pattern
- Screenshot-on-error pattern
- Proper use of selectors module
- Proper FlowResult construction
- Comments explaining each step

**Step 4: Create errors.py**

Error detection pattern:
```python
ERROR_SELECTORS = {
    "rate_limit": ".error-rate-limit",
    "content_blocked": ".error-content",
    "server_error": ".error-500",
}

async def detect_error(page) -> tuple[str, str] | None:
    """Check page for known error states. Returns (error_type, message) or None."""
    ...
```

**Step 5: Create README.md**

Guide for creating a new plugin:
1. Copy `_example/` to `plugins/your_plugin/`
2. Update manifest.json with real task types
3. Map real CSS selectors in selectors.py
4. Implement flows in flows.py
5. Add error detection in errors.py
6. Test with `python -m app.cli.auth --plugin your_plugin`

**Step 6: Commit**

```bash
git add plugins/_example/
git commit -m "feat: add example plugin template with documentation"
```

---

### Task 21: Example Job Spec

**Files:**
- Create: `examples/job_example.json`

**Step 1: Create job_example.json**

Demonstrates:
- Two "characters" using `VariantExpansion` with `expand_over`
- Multiple aspect ratios in the expansion
- `variants: 2` for multiple versions per combination
- `global_params` for style consistency
- A `PipelineStep` that feeds image outputs into an upscale task type
- `trigger_mode: "each"` on the pipeline step

```json
{
  "project_name": "character_concepts",
  "description": "Generate character concept art in multiple aspect ratios, then upscale",
  "expansions": [
    {
      "plugin": "example_service",
      "task_type": "generate_image",
      "param_template": {
        "prompt": "A {character} warrior in a fantasy landscape, {style}",
        "aspect_ratio": "{ratio}"
      },
      "expand_over": {
        "character": ["bull", "bear"],
        "ratio": ["1:1", "16:9"]
      },
      "variants": 2,
      "ref_id": "base_images"
    }
  ],
  "pipelines": [
    {
      "source_ref": "base_images",
      "plugin": "example_service",
      "task_type": "upscale_image",
      "param_template": {
        "input_image": "{artifact_path}",
        "scale_factor": "2x"
      },
      "trigger_mode": "each",
      "outputs_per_input": 1
    }
  ],
  "global_params": {
    "style": "cinematic lighting, detailed armor, 8k quality"
  },
  "naming_prefix": "char_concept"
}
```

**Step 2: Commit**

```bash
git add examples/job_example.json
git commit -m "feat: add example job spec demonstrating expansions and pipelines"
```

---

### Task 22: Caddyfile Example

**Files:**
- Create: `Caddyfile.example`

**Step 1: Create Caddyfile.example**

```
# Example Caddyfile for noapi behind Caddy reverse proxy
# Copy to /etc/caddy/Caddyfile and adjust domain

your-domain.com {
    reverse_proxy localhost:8000
}
```

**Step 2: Commit**

```bash
git add Caddyfile.example
git commit -m "docs: add example Caddyfile for reverse proxy"
```

---

### Task 23: README

**Files:**
- Create: `README.md`

**Step 1: Create README.md**

Sections:
1. What is noapi (brief description)
2. Architecture diagram (ASCII)
3. Quick Start (install, start server, start worker)
4. Configuration (env vars table)
5. Job Specs (link to example, explain structure)
6. Creating Plugins (link to example plugin README)
7. API Reference (endpoint table with methods and descriptions)
8. Deployment (Caddy, systemd hints)
9. Dashboard (screenshot placeholder, feature description)

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add project README with setup and usage instructions"
```

---

## Phase 7: Integration & Verification (Task 24)

### Task 24: Integration Smoke Test

**Step 1: Run all tests**

```bash
pytest tests/ -v
```

**Step 2: Start server and verify endpoints**

```bash
# Start server in background
python -m app.cli.server &
sleep 2

# Test health endpoint
curl -s http://localhost:8000/api/health | python -m json.tool

# Test plugin list (empty)
curl -s http://localhost:8000/api/plugins | python -m json.tool

# Test job submission (should fail — no plugins registered yet)
curl -s -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d @examples/job_example.json | python -m json.tool

# Test dashboard loads
curl -s http://localhost:8000/ | head -5

# Kill server
kill %1
```

**Step 3: Verify all files exist**

Check every file in the spec's folder structure exists and has content.

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: integration verification complete"
```

---

## Dependency Graph

```
Task 1 (scaffold) ─┬─> Task 2 (settings) ──> Task 3 (schemas) ──> Task 4 (DB)
                    │                                                    │
                    │    ┌───────────────────────────────────────────────┘
                    │    ▼
                    ├─> Task 5 (plugin registry)
                    │    │
                    │    ▼
                    ├─> Task 6 (scheduler) ──> Task 7 (pipeline)
                    │
                    ├─> Task 8 (QC)
                    │
                    │   (After Tasks 4-8 complete:)
                    │    │
                    │    ▼
                    ├─> Task 9 (FastAPI app shell)
                    │    │
                    │    ├─> Task 10 (health/workers/plugins routes)
                    │    ├─> Task 11 (task routes)
                    │    ├─> Task 12 (artifact routes)
                    │    └─> Task 13 (job routes)
                    │
                    │   (After Task 9:)
                    │    │
                    │    ▼
                    ├─> Task 14 (browser helpers) ──> Task 15 (remote worker) ──> Task 16 (CLI)
                    │
                    │   (Independent of API:)
                    │    │
                    │    ▼
                    ├─> Task 17 (HTML) ──> Task 18 (CSS) ──> Task 19 (JS)
                    │
                    ├─> Task 20 (example plugin)
                    ├─> Task 21 (example job spec)
                    ├─> Task 22 (Caddyfile)
                    ├─> Task 23 (README)
                    │
                    └─> Task 24 (integration test) — depends on ALL above
```

## Parallelization Opportunities

These groups can be worked on in parallel:
- **Group A**: Tasks 5, 6, 7, 8 (core services — after Task 4)
- **Group B**: Tasks 10, 11, 12, 13 (API routes — after Task 9, can be parallel with each other)
- **Group C**: Tasks 17, 18, 19 (dashboard — independent of API)
- **Group D**: Tasks 20, 21, 22, 23 (docs/examples — independent)
