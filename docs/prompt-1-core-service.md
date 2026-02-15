# noapi — Prompt 1: Core Service

You are an expert automation engineer. Build a production-minded v1 of **noapi**, a generic browser automation service that turns any UI-only website (no API available) into a programmable, queue-based automation system.

## Philosophy

noapi is **site-agnostic**. The core service handles queueing, workers, artifact storage, human intervention, and a dashboard. All site-specific logic lives in **plugins** that follow a standard interface. The core never references any specific website.

## IMPORTANT

- Do NOT implement anything that bypasses captchas, stealth fingerprinting, evades service protections, or violates access controls/ToS. If login/captcha/verification appears, pause and require human intervention.
- The VPS hosts the API + queue + dashboard. Playwright workers may run on the VPS OR on other machines that already have Playwright installed (preferred). Workers poll the VPS for tasks, run the browser steps locally, then upload artifacts back to the VPS.
- Keep deployment flexible: the service should run behind a reverse proxy (Caddy assumed) or standalone on localhost.

## Constraints & Tech Stack

- Linux VPS target (works on macOS/Windows for development).
- Python 3.11+.
- FastAPI for API + dashboard backend.
- SQLite for queue and artifact index (local disk).
- Playwright (Python) for workers.
- Pydantic v2 for all schemas.
- Standard logging module with structured (JSON-ish) logs.
- python-multipart for uploads.
- pathlib for all paths.
- uvicorn as the ASGI server.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                    VPS (Core)                        │
│                                                     │
│  FastAPI ─── SQLite Queue ─── Artifact Store        │
│     │                                               │
│  Dashboard (static HTML+JS served by FastAPI)       │
└──────────────┬──────────────────────────────────────┘
               │  HTTP (poll/claim/upload)
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 Worker 1   Worker 2   Worker N
 (any machine with Playwright)
 Loads site plugin, executes browser flows,
 uploads artifacts back to VPS
```

### Flow

1. **Job Spec (JSON)** describes what to generate: task types, parameters, variants, and optional pipeline dependencies (output of one task feeds into another).
2. **Scheduler** parses job spec, creates tasks in SQLite based on plugin-declared task types.
3. **Workers** (remote-capable) poll the VPS for tasks matching their plugin capability, execute browser automation flows defined by the plugin, and upload artifacts back.
4. **Artifact store** on VPS disk with metadata per artifact.
5. **Dashboard** for uploading job specs, viewing job/task states, previewing artifacts, and handling human intervention.

---

## Plugin Interface

This is the contract that site plugins must follow. The core service discovers and loads plugins at startup (workers load plugins locally).

### Plugin Structure

Each plugin is a Python package under `plugins/` with this structure:

```
plugins/
  {plugin_name}/
    __init__.py
    manifest.json          # Plugin metadata and capabilities
    selectors.py           # CSS selectors and DOM targets, organized by flow step
    flows.py               # Browser automation flow definitions
    errors.py              # Error detection and classification
    README.md              # Human-readable documentation
```

### manifest.json

```json
{
  "name": "example_service",
  "display_name": "Example Service",
  "version": "0.1.0",
  "documented_at": "2025-06-15",
  "auth_url": "https://example.com/login",
  "base_url": "https://example.com/app",
  "capabilities": {
    "task_types": [
      {
        "name": "generate_image",
        "description": "Generate an image from a text prompt",
        "params_schema": {
          "prompt": { "type": "string", "required": true },
          "aspect_ratio": { "type": "string", "required": false, "default": "1:1", "enum": ["1:1", "16:9", "9:16"] },
          "style_ref": { "type": "string", "required": false }
        },
        "artifact_kind": "image",
        "typical_duration_s": 60,
        "max_timeout_s": 300
      }
    ],
    "pipeline_support": true,
    "auth_method": "browser_session"
  }
}
```

### flows.py Interface

The base class and result types are defined in `app/schemas.py` so both core and plugins can import them.

```python
from abc import ABC, abstractmethod
from playwright.async_api import Page, BrowserContext
from typing import Any
# Plugins import from: from app.schemas import SiteFlowBase, FlowResult, NeedsHumanError, FlowError

class SiteFlowBase(ABC):
    """Base class all plugin flows must inherit from."""

    @abstractmethod
    async def execute(self, page: Page, task_payload: dict, download_dir: str) -> FlowResult:
        """
        Execute the browser automation flow for a task.

        Args:
            page: Playwright page instance (from persistent context)
            task_payload: The task's payload dict from the job spec
            download_dir: Local directory where artifacts should be saved

        Returns:
            FlowResult with status, artifact paths, and metadata

        Raises:
            NeedsHumanError: When login/captcha/verification is detected
            FlowError: When the flow fails but can be retried
        """
        pass

    @abstractmethod
    async def detect_auth_required(self, page: Page) -> bool:
        """Check if the current page state indicates auth is needed."""
        pass

    @abstractmethod
    async def health_check(self, page: Page) -> HealthCheckResult:
        """
        Attempt to load the base URL (no login) and report which
        key selectors are found/missing. Best-effort.
        """
        pass
```

### FlowResult / Error Types (defined in core)

```python
@dataclass
class FlowResult:
    success: bool
    artifact_paths: list[str]       # Local file paths of downloaded artifacts
    metadata: dict                  # Plugin-specific metadata (prompt used, params, etc.)
    screenshots: list[str]          # Any screenshots taken during the flow

class NeedsHumanError(Exception):
    """Raised when human intervention is required (login, captcha, etc.)."""
    def __init__(self, message: str, screenshot_path: str | None = None):
        self.message = message
        self.screenshot_path = screenshot_path

class FlowError(Exception):
    """Raised when flow fails but is retryable."""
    def __init__(self, message: str, screenshot_path: str | None = None):
        self.message = message
        self.screenshot_path = screenshot_path
```

### Plugin Discovery

- Workers specify which plugin to load via CLI flag: `--plugin midjourney`
- The worker imports `plugins.{name}.flows` and instantiates the flow class.
- The VPS core only needs the `manifest.json` from each plugin (to validate job specs and display capabilities in the dashboard). Provide a `POST /api/plugins/register` endpoint where workers can upload their plugin manifest on registration.

---

## Folder Structure (on VPS)

```
noapi/
  app/
    __init__.py
    main.py                  # FastAPI app
    settings.py              # Env config: base URLs, storage paths, etc.
    db.py                    # SQLite init + queries
    schemas.py               # Pydantic models: job spec, tasks, artifacts, API
    plugin_registry.py       # In-memory plugin manifest registry
    services/
      __init__.py
      scheduler.py           # Job ingestion -> task creation
      pipeline.py            # Dependency resolution: when task A completes, enqueue task B
    workers/
      __init__.py
      remote_worker.py       # Poll/claim loop + heartbeats + uploads
      browser.py             # Playwright context/session helpers, tracing, downloads
    qc/
      __init__.py
      basic.py               # File size threshold, hash de-dupe
    static/
      index.html
      app.js
      styles.css
    cli/
      __init__.py
      server.py              # uvicorn entry: python -m app.cli.server
      worker.py              # Worker CLI entry: python -m app.cli.worker
      auth.py                # Headed login helper: python -m app.cli.auth
  plugins/
    _example/                # Example/template plugin (not functional, for reference)
      __init__.py
      manifest.json
      selectors.py
      flows.py
      errors.py
      README.md
  data/
    queue.sqlite
    sessions/                # Playwright persistent user data dirs (on worker machines)
      {plugin_name}/
    jobs/
      {job_id}/
        job.json
        artifacts/
          images/
          videos/
          other/
        logs/
          api.log
          worker_{worker_id}.log
        screenshots/
          {task_id}_*.png
  examples/
    job_example.json         # Example job spec demonstrating the schema
  README.md
  requirements.txt
  Caddyfile.example
```

---

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,              -- uuid
    job_id TEXT NOT NULL,
    plugin TEXT NOT NULL,             -- plugin name (from manifest)
    task_type TEXT NOT NULL,          -- declared in plugin manifest
    payload_json TEXT NOT NULL,       -- JSON: task-specific parameters
    status TEXT NOT NULL DEFAULT 'queued',
        -- 'queued' | 'running' | 'completed' | 'failed' | 'needs_human' | 'blocked'
    depends_on_task_id TEXT,          -- NULL or task ID this depends on
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    assigned_worker_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,              -- uuid
    job_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    plugin TEXT NOT NULL,
    kind TEXT NOT NULL,               -- 'image' | 'video' | 'screenshot' | 'other'
    filepath TEXT NOT NULL,           -- VPS local path
    original_filename TEXT,
    sha256 TEXT,
    file_size_bytes INTEGER,
    is_duplicate BOOLEAN DEFAULT FALSE,
    metadata_json TEXT,               -- Plugin-specific metadata
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,              -- uuid
    project_name TEXT,
    spec_json TEXT NOT NULL,          -- Original job spec JSON
    status TEXT NOT NULL DEFAULT 'active',
        -- 'active' | 'completed' | 'failed' | 'cancelled'
    total_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    hostname TEXT,
    plugin TEXT,                      -- Which plugin this worker runs
    capabilities_json TEXT,           -- { headed: bool, ... }
    last_seen_at TEXT,
    registered_at TEXT NOT NULL
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_job_id ON tasks(job_id);
CREATE INDEX idx_tasks_plugin ON tasks(plugin);
CREATE INDEX idx_artifacts_job_id ON artifacts(job_id);
CREATE INDEX idx_artifacts_task_id ON artifacts(task_id);
```

---

## API Endpoints

### Jobs
- `POST /api/jobs` — Submit a job spec (JSON body or multipart upload). Validates all `plugin` and `task_type` values against registered plugin manifests, validates `params` against the manifest's `params_schema`. Creates tasks via scheduler.
- `GET /api/jobs` — List all jobs with summary counts.
- `GET /api/jobs/{job_id}` — Job detail with task breakdown by status.
- `POST /api/jobs/{job_id}/cancel` — Cancel all queued tasks in a job.

### Tasks
- `GET /api/tasks?job_id=...&status=...` — List tasks with optional filters.
- `POST /api/tasks/{task_id}/retry` — Reset task to queued (for needs_human resolution). Sets status='queued', clears last_error.

### Artifacts
- `GET /api/artifacts?job_id=...&task_id=...&kind=...` — List artifacts with optional filters. Returns artifact metadata including download URLs (relative paths served by FastAPI static file mount).
- `GET /api/artifacts/{artifact_id}/download` — Download an artifact file directly.

### Workers
- `POST /api/workers/register` — Register a worker. Must include the plugin's `manifest_json` on first registration (this is how the server learns about plugins — workers carry their plugin manifests). Subsequent registrations from the same worker can omit it.
  Body: `{ worker_id, hostname, plugin, capabilities: { headed: bool }, manifest_json: {...} | null }`
- `POST /api/tasks/claim` — Atomically claim a queued task.
  Body: `{ worker_id, plugin }`
  Returns: `{ task }` or `{ task: null }`
  Claim sets `status='running'`, `assigned_worker_id`, `heartbeat_at=now`.
  Only returns tasks where `depends_on_task_id` is NULL or the dependency is completed.
- `POST /api/tasks/{task_id}/heartbeat` — Worker heartbeat.
  Body: `{ worker_id }`
- `POST /api/tasks/{task_id}/complete` — Mark task completed.
  Body: `{ worker_id, result_json }`
  After completion, trigger pipeline resolution:
    - For pipelines with `trigger_mode="each"`: immediately create a downstream task using this task's artifacts.
    - For pipelines with `trigger_mode="all"`: check if all tasks sharing the source_ref are now completed. If yes, create downstream task(s) with all artifact paths. If not, do nothing yet.
- `POST /api/tasks/{task_id}/fail` — Mark task failed.
  Body: `{ worker_id, error, needs_human: bool, screenshot_path: str | null }`
  If `needs_human=true`: set status='needs_human', store screenshot.
  Else if `attempts < max_attempts`: requeue with incremented attempts.
  Else: set status='failed'.
- `POST /api/upload/{job_id}/{task_id}` — Upload artifact files (multipart).
  Store in `data/jobs/{job_id}/artifacts/{kind}/`.
  Compute sha256, check for duplicates, insert artifact record.

### Plugins
- `GET /api/plugins` — List registered plugin manifests (populated when workers register).
- `GET /api/plugins/{name}` — Get a specific plugin manifest including full params_schema for each task type.

### Health
- `GET /api/health` — Service health check (DB connectivity, disk space).
- `GET /api/health/selectors?plugin={name}` — Trigger a best-effort selector health check for a plugin (if a worker is available). Returns which key selectors were found/missing.

---

## Job Spec Schema (Pydantic)

The job spec is generic but structured. Plugins define what task types and parameters they support; the job spec references those.

```python
class TaskSpec(BaseModel):
    """A single task to create."""
    plugin: str                              # Plugin name
    task_type: str                           # Must match a task_type in plugin manifest
    params: dict[str, Any]                   # Parameters as defined in plugin's params_schema
    depends_on: str | None = None            # Reference to another task_spec by its ref_id
    ref_id: str | None = None                # Local reference ID for dependency linking

class VariantExpansion(BaseModel):
    """
    Generate multiple tasks from a template with variable expansion.
    This is the primary way to create batch jobs.
    """
    plugin: str
    task_type: str
    param_template: dict[str, Any]           # Params with {variable} placeholders
    expand_over: dict[str, list[Any]]        # Variables to expand: { "character": ["bull","bear"], "ratio": ["1:1","16:9"] }
    variants: int = 1                        # Number of variants per combination
    depends_on: str | None = None
    ref_id: str | None = None                # All expanded tasks share this ref for dependency

class PipelineStep(BaseModel):
    """
    Define a pipeline: when tasks with source_ref complete,
    auto-create tasks using their artifacts as input.
    """
    source_ref: str                          # ref_id of the upstream task group
    plugin: str
    task_type: str
    param_template: dict[str, Any]           # Can reference {artifact_path} from upstream
    outputs_per_input: int = 1
    trigger_mode: str = "each"               # "each" or "all"
        # "each": create downstream task(s) every time a single upstream task completes.
        #         {artifact_path} resolves to that task's artifact.
        # "all":  wait until ALL tasks sharing source_ref are completed,
        #         then create downstream task(s). {artifact_paths} (plural) available
        #         as a list. Useful when you want to select the best result or
        #         need all outputs before proceeding.

class JobSpec(BaseModel):
    project_name: str
    description: str | None = None
    tasks: list[TaskSpec] = []               # Explicit individual tasks
    expansions: list[VariantExpansion] = []   # Batch task generation
    pipelines: list[PipelineStep] = []       # Cross-plugin pipelines
    global_params: dict[str, Any] = {}       # Merged into all task params as defaults
    naming_prefix: str | None = None         # Prefix for deterministic filenames
```

### Task Creation Rules

- For each `TaskSpec`: create one task.
- For each `VariantExpansion`: compute the cartesian product of `expand_over` values, multiply by `variants`, create one task per combination.
- For `PipelineStep`: don't create tasks at submission time. Behavior depends on `trigger_mode`:
  - `"each"` (default): every time a task with matching `source_ref` completes, immediately create downstream task(s) with `{artifact_path}` resolved to that task's artifact. This means N upstream completions produce N downstream tasks.
  - `"all"`: wait until every task sharing the `source_ref` ref_id has status='completed'. Then create downstream task(s) with `{artifact_paths}` available as a JSON list of all artifact paths. Useful for selection/QC logic before the next stage.
- Validate all `plugin` and `task_type` values against registered manifests at submission time. Reject with clear errors if unknown.

---

## Deterministic Naming

Artifacts are named by the core (not plugins) using a deterministic scheme:

```
{naming_prefix}_{plugin}_{task_type}_{variant:03d}_{hash8}_{ts}.{ext}
```

Where:
- `naming_prefix`: from job spec or job_id if not set
- `plugin`: plugin name
- `task_type`: short task type
- `variant`: zero-padded variant number
- `hash8`: first 8 chars of sha256 (for uniqueness)
- `ts`: compact timestamp (YYYYMMDD_HHMMSS)
- `ext`: file extension

Save a sidecar JSON alongside each artifact:
```
same_filename.json  ->  { "prompt": "...", "params": {...}, "plugin": "...", "task_id": "...", "job_id": "...", "created_at": "..." }
```

---

## Worker Implementation

### CLI

```bash
# Start worker (polls VPS for tasks, runs plugin flows locally)
python -m app.cli.worker \
  --server https://your-vps.com \
  --plugin example_service \
  --worker-id worker1 \
  --headed                          # or --headless (default: headed)

# Auth helper (opens browser for manual login, saves session)
python -m app.cli.auth \
  --plugin example_service \
  --headed
```

### Worker Loop (remote_worker.py)

```
1. Register with VPS: POST /api/workers/register (include plugin manifest)
2. Loop:
   a. POST /api/tasks/claim { worker_id, plugin }
   b. If no task: sleep(poll_interval), continue
   c. Load plugin flow class
   d. Create Playwright persistent context from local session dir
   e. Start heartbeat thread (POST heartbeat every 30s)
   f. Try:
        result = await flow.execute(page, task.payload, download_dir)
        Upload artifacts: POST /api/upload/{job_id}/{task_id}
        Report: POST /api/tasks/{task_id}/complete { result_json }
      Except NeedsHumanError:
        Save screenshot locally + upload to VPS
        POST /api/tasks/{task_id}/fail { needs_human: true, error, screenshot }
      Except FlowError:
        Save screenshot + upload
        POST /api/tasks/{task_id}/fail { needs_human: false, error }
      Except Exception:
        Save screenshot + upload
        POST /api/tasks/{task_id}/fail { needs_human: false, error }
   g. Stop heartbeat thread
3. On shutdown: graceful cleanup
```

### Playwright Session Management (browser.py)

- Persistent context directories are LOCAL to the worker machine:
  - `WORKER_SESSION_ROOT` env var (default: `./sessions/`)
  - Within that: `{plugin_name}/` directories
- Provide helpers:
  - `create_persistent_context(plugin_name, headed=True)` -> BrowserContext
  - `screenshot_on_error(page, task_id, screenshot_dir)` -> str (path)
  - `wait_with_timeout(page, selector, timeout_s)` with clear error messages
  - `download_artifact(page, download_trigger, download_dir)` -> str (path)
- Worker auth helper opens the plugin's `auth_url` in headed mode, waits for human to login, then exits. Session persists in the user data dir.

### Heartbeat & Stale Task Recovery

- Workers send heartbeats every 30 seconds.
- The server has a background task that checks for stale running tasks (heartbeat_at older than 2 minutes). Stale tasks are requeued if attempts < max_attempts, otherwise failed.

---

## Dashboard

Serve static UI from FastAPI at `/`.

### index.html Requirements

- File upload for job spec JSON (with validation feedback).
- List of jobs with status summary (tasks by status, progress bar).
- Job detail view: task table with status, plugin, type, assigned worker.
- "Needs Human" section: tasks requiring intervention, showing screenshot previews, error messages, and Retry/Resolve buttons.
- Artifacts grid: image/video previews with download links and metadata.
- Workers panel: registered workers, last seen, plugin, status.
- Plugins panel: registered plugins with capabilities summary.

### app.js

- Poll `/api/jobs` and current job detail every 3 seconds.
- Use vanilla JS (no framework). Keep it simple.
- Provide tab-based navigation: Jobs | Workers | Plugins.

---

## Security

- **Worker auth**: Single env var `NOAPI_WORKER_KEY`. Required in `X-Worker-Key` header for all worker endpoints (register, claim, heartbeat, complete, fail, upload).
- **Dashboard auth**: Optional `NOAPI_BASIC_AUTH` env var (format: `user:password`). If set, protect dashboard and job API routes with HTTP Basic Auth.
- **No credentials in code**: Browser sessions are the only auth mechanism for target sites. Stored in Playwright user data dirs on worker machines.
- **CORS**: Configurable `NOAPI_CORS_ORIGINS` env var. Default: allow same-origin only.

---

## Deployment

### Environment Variables

```
NOAPI_HOST=0.0.0.0
NOAPI_PORT=8000
NOAPI_DATA_DIR=./data
NOAPI_WORKER_KEY=your-secret-key
NOAPI_BASIC_AUTH=                    # Optional: user:password
NOAPI_CORS_ORIGINS=                  # Optional: comma-separated origins
NOAPI_LOG_LEVEL=INFO
NOAPI_ROOT_PATH=                     # For reverse proxy path prefix (FastAPI root_path)
NOAPI_BASE_URL=http://localhost:8000 # Externally reachable URL
```

### Caddyfile Example

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

### Startup

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Start server
python -m app.cli.server

# On worker machine(s):
# 1. First-time auth
python -m app.cli.auth --plugin example_service --headed
# 2. Start worker
python -m app.cli.worker --server https://your-domain.com --plugin example_service --worker-id w1 --headed
```

---

## Example Job Spec

Provide `examples/job_example.json` that demonstrates the schema using a hypothetical plugin. Show:
- Two "characters" using VariantExpansion with expand_over
- Multiple aspect ratios
- A pipeline step that takes image outputs and feeds them into a second task type
- Global params for style consistency

---

## Example Plugin Template

Provide `plugins/_example/` as a fully commented reference plugin:
- `manifest.json` with two task types
- `selectors.py` with placeholder selectors and comments explaining the pattern
- `flows.py` with a skeleton `SiteFlowBase` implementation showing the expected structure, including auth detection and screenshot-on-error patterns
- `errors.py` with the error detection pattern
- `README.md` explaining how to create a new plugin

---

## Output Quality Controls

- On artifact upload, compute sha256 and record file size.
- If sha256 matches an existing artifact in the same job, mark `is_duplicate=true` in metadata.
- Optional file size threshold (configurable): flag suspiciously small files (likely errors).

---

## Deliverables

- All source files as described in the folder structure. Working API + dashboard + worker CLI.
- No placeholders for core plumbing (queueing, uploads, state transitions, API, dashboard, pipeline resolution, plugin loading).
- The `_example` plugin should be a well-commented template, not a functional automation.
- README with install, setup, run, and example workflow instructions.
- `requirements.txt` with pinned major versions.
