# noapi

A site-agnostic browser automation service that turns UI-only websites into programmable, queue-based automation systems. Define what you want done in a JSON job spec, and remote Playwright workers execute the browser flows, uploading artifacts back to a central server. All site-specific logic lives in plugins.

## Architecture

```
VPS (Core Server)
+---------------------------------------------------+
|  FastAPI                                          |
|    +-- SQLite Queue (WAL mode, async via aiosqlite)|
|    +-- Artifact Store (data/jobs/{id}/artifacts/) |
|    +-- Plugin Registry (in-memory)                |
|    +-- Stale Task Recovery (background loop)      |
|    +-- Dashboard (static HTML+JS+CSS)             |
+------------------------+--------------------------+
                         | HTTP (poll/claim/upload)
              +----------+----------+
              v          v          v
           Worker 1   Worker 2   Worker N
           (Playwright on any machine)
           (persistent browser sessions)
```

**Core server** runs on a VPS: receives job specs via REST API, expands variants into individual tasks, queues them in SQLite, stores uploaded artifacts with deterministic naming, resolves pipeline dependencies, and serves a live dashboard.

**Workers** run anywhere with a browser: register with the server, poll for tasks matching their plugin, execute plugin-defined browser flows via Playwright, and upload result artifacts back. Workers maintain persistent browser sessions for sites requiring authentication.

**Plugins** are Python packages under `plugins/` that define CSS selectors, browser flows, and error detection for a specific site. A plugin handles one site and declares its capabilities in a `manifest.json`.

## Project Structure

```
noapi/
  app/
    cli/
      auth.py              # One-time browser session saver
      server.py            # Uvicorn launcher
      worker.py            # Worker process with poll loop
    routes/
      artifacts.py         # Upload, list, download artifacts
      health.py            # Server + selector health checks
      jobs.py              # Submit, list, cancel jobs
      plugins.py           # Plugin manifest registry
      tasks.py             # Claim, heartbeat, complete, fail, retry
      workers.py           # Worker registration + listing
    services/
      pipeline.py          # Pipeline resolution + input selectors
      scheduler.py         # Variant expansion + task creation
    workers/
      browser.py           # Playwright helpers (context, download, screenshot)
      remote_worker.py     # HTTP client for worker-to-server comms
    qc/
      basic.py             # SHA-256 hashing, file size checks, naming
    static/
      index.html           # Dashboard SPA
      app.js               # Dashboard JavaScript
      styles.css            # Dashboard styles
    db.py                  # Async SQLite layer (aiosqlite)
    main.py                # FastAPI app, middleware, lifespan
    plugin_registry.py     # In-memory manifest store
    schemas.py             # All Pydantic models + plugin base classes
    settings.py            # Environment variable configuration
  plugins/
    _example/              # Template plugin (copy to create your own)
      manifest.json        # Task types, param schemas, timing hints
      flows.py             # SiteFlowBase subclass
      selectors.py         # CSS selectors organized by flow
      errors.py            # Error detection utilities
      README.md            # Plugin development guide
  tests/
    test_db.py             # Database layer tests
    test_scheduler.py      # Variant expansion + task creation tests
    test_pipeline.py       # Pipeline resolution + input selector tests
    test_naming.py         # Deterministic artifact naming tests
  examples/
    job_example.json       # Full job spec with expansions + pipelines
  docs/
    plans/                 # Design documents and implementation plans
  Caddyfile.example        # Reverse proxy config template
  requirements.txt         # Python dependencies
```

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**Requirements:** Python 3.9+, Chromium (installed via Playwright).

**Dependencies:** FastAPI, uvicorn, aiosqlite, Pydantic v2, httpx, python-multipart, Playwright.

### 2. Start the server

```bash
python -m app.cli.server
```

The server starts on `http://localhost:8000` by default. The dashboard is available at the root URL.

### 3. Save a browser session (one-time per plugin)

```bash
python -m app.cli.auth --plugin example_service
```

A headed browser opens. Log in to the target site manually, then close the browser. The session is saved to `./sessions/example_service/` for the worker to reuse.

### 4. Start a worker

```bash
python -m app.cli.worker \
  --server http://localhost:8000 \
  --plugin example_service \
  --worker-id worker-1 \
  --headed
```

The worker registers with the server, uploads the plugin manifest, and begins polling for tasks. Use `--headless` for production.

### 5. Submit a job

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d @examples/job_example.json
```

Or use the dashboard to upload a job spec JSON file.

## Configuration

All settings are controlled via environment variables:

| Variable | Description | Default |
|---|---|---|
| `NOAPI_HOST` | Server bind address | `0.0.0.0` |
| `NOAPI_PORT` | Server port | `8000` |
| `NOAPI_DATA_DIR` | Directory for SQLite DB, artifacts, sessions | `./data` |
| `NOAPI_WORKER_KEY` | Shared secret for worker authentication (empty = no auth) | `""` |
| `NOAPI_BASIC_AUTH` | HTTP Basic Auth for dashboard in `user:password` format (empty = no auth) | `""` |
| `NOAPI_CORS_ORIGINS` | Comma-separated allowed CORS origins | `""` |
| `NOAPI_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `NOAPI_ROOT_PATH` | Root path for reverse proxy setups | `""` |
| `NOAPI_BASE_URL` | Public base URL of the server | `http://localhost:8000` |

Workers also use:

| Variable | Description | Default |
|---|---|---|
| `WORKER_SESSION_ROOT` | Directory for persistent browser sessions | `./sessions` |

## Job Specs

A job spec is a JSON document that describes what work to do. It supports three ways to define tasks, which can be combined in a single spec.

### Explicit tasks

Direct task definitions with fixed parameters:

```json
{
  "project_name": "my_project",
  "tasks": [
    {
      "plugin": "example_service",
      "task_type": "generate_image",
      "params": { "prompt": "a sunset over mountains" }
    }
  ]
}
```

Each task can optionally include:
- `ref_id` -- tag for pipeline chaining (downstream steps reference this)
- `depends_on` -- ref_id of an upstream task group (task stays blocked until dependency completes)

### Variant expansions

Generate a cartesian product of parameter combinations:

```json
{
  "project_name": "batch_run",
  "expansions": [
    {
      "plugin": "example_service",
      "task_type": "generate_image",
      "param_template": {
        "prompt": "A {subject} in {setting}, {style}",
        "aspect_ratio": "{ratio}"
      },
      "expand_over": {
        "subject": ["cat", "dog"],
        "ratio": ["1:1", "16:9"]
      },
      "variants": 2,
      "ref_id": "base_images"
    }
  ],
  "global_params": {
    "setting": "a forest",
    "style": "watercolor"
  }
}
```

This creates `2 subjects * 2 ratios * 2 variants = 8` tasks. The `global_params` are merged into each task's parameters -- placeholders like `{setting}` and `{style}` in `param_template` are resolved from `global_params`.

**Expansion fields:**

| Field | Description |
|---|---|
| `plugin` | Plugin to handle these tasks |
| `task_type` | Task type from the plugin manifest |
| `param_template` | Template with `{placeholder}` values |
| `expand_over` | Map of placeholder name to list of values (cartesian product) |
| `variants` | Number of duplicate tasks per combination (default: 1) |
| `ref_id` | Tag for pipeline chaining |
| `depends_on` | Ref_id of upstream task group |

### Pipelines

Chain task outputs into downstream tasks:

```json
{
  "pipelines": [
    {
      "source_ref": "base_images",
      "plugin": "example_service",
      "task_type": "upscale_image",
      "param_template": {
        "input_image": "{artifact_path}",
        "scale_factor": "2x"
      },
      "input_selector": {
        "kind": "image",
        "pick": "first"
      },
      "trigger_mode": "each",
      "outputs_per_input": 1
    }
  ]
}
```

**Input selectors** control which upstream artifacts feed into the pipeline step:

- `kind` -- filter artifacts by kind: `"image"`, `"video"`, `"screenshot"`, or `"any"` (default). This ensures screenshots or other non-primary outputs don't accidentally become pipeline inputs.
- `pick` -- select from filtered artifacts: `"first"` (default, stable ordering by creation time) or `"all"`.

**Trigger modes:**

- `trigger_mode: "each"` -- create downstream tasks as each upstream task completes.
- `trigger_mode: "all"` -- wait for all upstream tasks with the `source_ref` to complete, then create downstream tasks.

**Template variables** available in `param_template`:

| Variable | Description |
|---|---|
| `{artifact_id}` | ID of first selected artifact |
| `{artifact_path}` | File path of first selected artifact |
| `{artifact_kind}` | Kind of first selected artifact |
| `{artifact_ids}` | JSON array of all selected artifact IDs |
| `{artifact_paths}` | JSON array of all selected artifact file paths |

**`outputs_per_input`** controls how many downstream tasks are created per upstream artifact set (default: 1). Useful when one upstream image should produce multiple downstream variants.

### Complete example

See [`examples/job_example.json`](examples/job_example.json) for a full spec combining expansions with both `"each"` and `"all"` pipeline modes.

### Job-level fields

| Field | Description |
|---|---|
| `project_name` | Human-readable project label |
| `description` | Optional description |
| `tasks` | Explicit task list |
| `expansions` | Variant expansion definitions |
| `pipelines` | Pipeline step definitions |
| `global_params` | Parameters merged into all tasks/expansions |
| `naming_prefix` | Prefix for deterministic artifact filenames |

## Artifact System

### ArtifactSpec objects

Plugins return explicit `ArtifactSpec` objects from their `execute()` method. Each artifact carries:

| Field | Description |
|---|---|
| `kind` | `"image"`, `"video"`, `"screenshot"`, or `"other"` |
| `local_path` | Absolute path on the worker machine |
| `filename_hint` | Optional suggested name (informational only, server ignores for naming) |
| `metadata` | Per-artifact metadata dict (stored in sidecar JSON) |

```python
FlowResult(
    success=True,
    artifacts=[
        ArtifactSpec(
            kind="image",
            local_path="/tmp/result.png",
            filename_hint="landscape.png",
            metadata={"prompt": "mountains", "seed": 42},
        )
    ],
    metadata={"total_time_s": 12.5},
)
```

### Server-owned naming and storage

The **server owns all artifact naming and storage**. Plugins and workers never decide final filenames. On upload, the server:

1. **Stores** artifacts into `data/jobs/{job_id}/artifacts/{kind}/` (organized by kind subdirectory)
2. **Renames** files deterministically: `{prefix}_{plugin}_{task_type}_{variant:03d}_{hash8}_{timestamp}.{ext}`
3. **Writes** a sidecar JSON file next to each artifact with full provenance metadata (job_id, task_id, plugin, task_type, sha256, file_size, task_metadata, artifact_metadata)
4. **Detects** duplicates by SHA-256 within the same job (marked `is_duplicate=true` but still stored)

The upload endpoint accepts:
- `files` -- one or more files (multipart)
- `artifacts_manifest` -- JSON array with per-file `kind`, `filename_hint`, and `metadata`
- `task_metadata` -- JSON object with task-level metadata (written into every sidecar)

### Quality checks

- SHA-256 hash computed on upload for integrity and deduplication
- File size validation available via `check_file_size()` utility

## Creating Plugins

Each plugin lives in its own directory under `plugins/`:

```
plugins/your_plugin/
  __init__.py          # Empty (required for Python package)
  manifest.json        # Plugin metadata and task type definitions
  selectors.py         # CSS selectors organized by flow
  flows.py             # SiteFlowBase subclass with browser automation
  errors.py            # Error detection utilities
```

### manifest.json

Declares what your plugin can do:

```json
{
  "name": "your_plugin",
  "display_name": "Your Plugin",
  "version": "0.1.0",
  "auth_url": "https://example.com/login",
  "base_url": "https://example.com/app",
  "capabilities": {
    "task_types": [
      {
        "name": "generate_image",
        "description": "Generate an image from a text prompt",
        "params_schema": {
          "prompt": { "type": "string", "required": true },
          "aspect_ratio": {
            "type": "string",
            "required": false,
            "default": "1:1",
            "enum": ["1:1", "16:9", "9:16"]
          }
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

### flows.py

Your flow class must inherit from `SiteFlowBase` and implement three methods:

```python
from app.schemas import (
    ArtifactSpec, FlowError, FlowResult,
    HealthCheckResult, NeedsHumanError, SiteFlowBase,
)

class YourPluginFlow(SiteFlowBase):
    async def execute(self, page, task_payload: dict, download_dir: str) -> FlowResult:
        """Run the browser automation. Return artifacts on success."""
        # 1. Navigate to the page
        # 2. Fill forms, click buttons, wait for results
        # 3. Download output files
        # 4. Return FlowResult with ArtifactSpec objects
        ...

    async def detect_auth_required(self, page) -> bool:
        """Return True if the current page shows a login wall."""
        ...

    async def health_check(self, page) -> HealthCheckResult:
        """Check which CSS selectors are present on the live site."""
        ...
```

**Error handling:**
- Raise `NeedsHumanError("message", screenshot_path)` when login, captcha, or manual intervention is needed. The task enters `needs_human` status and appears in the dashboard with the screenshot.
- Raise `FlowError("message", screenshot_path)` for retryable errors. The task is requeued up to `max_attempts` (default 3).

**Browser helpers** available from `app.workers.browser`:
- `download_artifact(page, trigger_callable, download_dir)` -- trigger a download and save the file
- `screenshot_on_error(page, task_id, screenshot_dir)` -- full-page screenshot for debugging
- `wait_with_timeout(page, selector, timeout_ms)` -- wait for a selector with a clear error message

### selectors.py

Keep all CSS selectors in one file for easy maintenance:

```python
# Login
LOGIN_FORM = "form[action*='login']"
LOGGED_IN_INDICATOR = "[data-testid='user-menu']"

# Generation flow
PROMPT_INPUT = "textarea[name='prompt']"
GENERATE_BUTTON = "button:has-text('Generate')"
RESULT_IMAGE = "img.result-image"
DOWNLOAD_BUTTON = "a[download]"
```

### errors.py

Centralize error detection:

```python
async def detect_error(page):
    """Check for site-specific error states. Returns (error_type, message) or None."""
    rate_limit = await page.query_selector(".rate-limit-message")
    if rate_limit:
        text = await rate_limit.inner_text()
        return ("rate_limit", text)
    return None
```

### Testing your plugin

```bash
# 1. Save your browser session (manual login)
python -m app.cli.auth --plugin your_plugin --headed

# 2. Start the server
python -m app.cli.server

# 3. Start a worker in headed mode to watch the automation
python -m app.cli.worker \
  --server http://localhost:8000 \
  --plugin your_plugin \
  --worker-id test-1 \
  --headed

# 4. Submit a test job
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"project_name":"test","tasks":[{"plugin":"your_plugin","task_type":"generate_image","params":{"prompt":"test"}}]}'
```

See [`plugins/_example/README.md`](plugins/_example/README.md) for a detailed step-by-step guide.

## Task Lifecycle

```
queued --> running --> completed
  ^          |             |
  |          v             v
  +------ failed      [pipeline resolution]
  |       (retry)          |
  |                        v
  +---- needs_human    downstream tasks
         (manual        (queued)
          retry)
```

**States:**

| Status | Description |
|---|---|
| `queued` | Waiting to be claimed by a worker |
| `blocked` | Waiting for a dependency (`depends_on`) to complete |
| `running` | Claimed by a worker, actively executing |
| `completed` | Finished successfully, artifacts uploaded |
| `failed` | Failed after all retry attempts exhausted |
| `needs_human` | Requires manual intervention (login, captcha, etc.) |
| `cancelled` | Cancelled via job cancellation |

**Retry behavior:** Failed tasks are automatically requeued up to `max_attempts` (default 3). After exhausting retries, the task enters `failed` status.

**Stale task recovery:** A background loop runs every 60 seconds. Tasks in `running` status with no heartbeat for 120 seconds are considered stale. They are requeued if attempts remain, or marked `failed` if exhausted.

**Heartbeats:** Workers send heartbeats every 30 seconds while executing a task. The server uses this to detect dead workers.

## API Reference

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Server health check (DB connectivity, disk space) |
| `GET` | `/api/health/selectors` | Selector health check for a plugin (`?plugin=name`) |

### Jobs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Submit a job spec (JSON body). Returns job_id and created task count. |
| `GET` | `/api/jobs` | List all jobs with summary counts (total, completed, failed tasks) |
| `GET` | `/api/jobs/{job_id}` | Get job detail with task breakdown by status |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel all queued/blocked tasks in a job |

### Tasks

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tasks` | List tasks (`?job_id=`, `?status=`, `?plugin=`) |
| `POST` | `/api/tasks/claim` | Atomically claim a queued task (worker endpoint). Body: `{"worker_id": "...", "plugin": "..."}` |
| `POST` | `/api/tasks/{task_id}/heartbeat` | Worker heartbeat to prevent stale-task recovery. Body: `{"worker_id": "..."}` |
| `POST` | `/api/tasks/{task_id}/complete` | Mark task completed, triggers pipeline resolution. Body: `{"worker_id": "...", "result_json": {...}}` |
| `POST` | `/api/tasks/{task_id}/fail` | Mark task failed or needs_human. Body: `{"worker_id": "...", "error": "...", "needs_human": false}` |
| `POST` | `/api/tasks/{task_id}/retry` | Reset a needs_human task back to queued |

### Artifacts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/artifacts` | List artifacts (`?job_id=`, `?task_id=`, `?kind=`) |
| `GET` | `/api/artifacts/{artifact_id}/download` | Download an artifact file |
| `POST` | `/api/upload/{job_id}/{task_id}` | Upload artifact files (worker endpoint, multipart). Fields: `files`, `artifacts_manifest` (JSON), `task_metadata` (JSON) |

### Workers

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/workers/register` | Register a worker and upload plugin manifest. Body: `{"worker_id": "...", "plugin": "...", "manifest_json": {...}}` |
| `GET` | `/api/workers` | List registered workers with last-seen timestamps |

### Plugins

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/plugins` | List all registered plugin manifests |
| `GET` | `/api/plugins/{name}` | Get a specific plugin manifest |

## Dashboard

The built-in dashboard is a single-page application served at the root URL. It provides:

- **Jobs tab** -- Submit job specs (paste or upload JSON), view job list with progress bars, drill into job details with task breakdowns by status, view artifacts in a grid layout with download links.
- **Workers tab** -- Monitor worker status, see which plugin each worker handles, track online/stale status based on heartbeat timestamps.
- **Plugins tab** -- Browse registered plugin manifests and their task type capabilities.
- **Needs Human** -- Jobs with tasks requiring human intervention are highlighted. Error screenshots and messages are displayed with a retry button.

The dashboard polls the API every 3 seconds for live updates. No build step required -- it is plain HTML, JavaScript, and CSS.

## Deployment

### Reverse Proxy with Caddy

Copy the included example and replace the domain:

```bash
cp Caddyfile.example /etc/caddy/Caddyfile
# Edit /etc/caddy/Caddyfile and replace "your-domain.com"
sudo systemctl reload caddy
```

Caddy automatically provisions TLS certificates via Let's Encrypt.

### systemd Service (server)

```ini
[Unit]
Description=noapi server
After=network.target

[Service]
Type=simple
User=noapi
WorkingDirectory=/opt/noapi
Environment=NOAPI_WORKER_KEY=your-secret-key
Environment=NOAPI_DATA_DIR=/opt/noapi/data
ExecStart=/opt/noapi/.venv/bin/python -m app.cli.server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### systemd Service (worker)

```ini
[Unit]
Description=noapi worker
After=network.target

[Service]
Type=simple
User=noapi
WorkingDirectory=/opt/noapi
Environment=NOAPI_WORKER_KEY=your-secret-key
ExecStart=/opt/noapi/.venv/bin/python -m app.cli.worker --server https://your-domain.com --plugin your_plugin --worker-id worker-1 --headless
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Multi-worker setup

Run multiple workers on different machines (or the same machine with different `--worker-id` values). Each worker handles one plugin. Workers can be added or removed at any time -- the server assigns tasks via atomic claim.

```bash
# Machine A: handles image generation
python -m app.cli.worker --server https://your-domain.com --plugin image_gen --worker-id gen-1 --headless

# Machine B: handles upscaling
python -m app.cli.worker --server https://your-domain.com --plugin upscaler --worker-id upscale-1 --headless
```

## Security

- **Worker authentication** -- Set `NOAPI_WORKER_KEY` to a shared secret. Workers must include it in the `X-Worker-Key` header. All worker endpoints (claim, heartbeat, complete, fail, upload, register) are protected. Uses constant-time comparison.
- **Dashboard authentication** -- Set `NOAPI_BASIC_AUTH` to `user:password` to require HTTP Basic Auth for the dashboard and job management API endpoints.
- **Browser sessions** -- Playwright persistent sessions are stored locally on each worker machine (never uploaded to the server). Each plugin gets its own isolated session directory.
- **TLS** -- Use a reverse proxy (Caddy, nginx) to terminate TLS. The server itself runs plain HTTP on localhost.
- **Health endpoint** -- `/api/health` is always publicly accessible (no auth required) for monitoring.
- **Plugin GET endpoints** -- `/api/plugins` is accessible without worker key so the dashboard can display manifests.

## Testing

```bash
# Run all tests
python -m pytest

# Run specific test files
python -m pytest tests/test_db.py          # Database layer (20 tests)
python -m pytest tests/test_scheduler.py   # Variant expansion + scheduling (9 tests)
python -m pytest tests/test_pipeline.py    # Pipeline resolution + selectors (9 tests)
python -m pytest tests/test_naming.py      # Artifact naming (4 tests)
```

All tests use an in-memory SQLite database and require no external services.

## Changelog

### v0.2.0 -- Artifact objects, server-owned naming, pipeline selectors

**Artifact objects.** Plugins now return explicit `ArtifactSpec` objects from `execute()` instead of bare file paths. Each artifact carries a `kind` (image, video, screenshot, other), `local_path`, optional `filename_hint`, and per-artifact `metadata` dict. The old `FlowResult.artifact_paths` and `FlowResult.screenshots` fields are replaced by a single `FlowResult.artifacts` list.

**Server-owned naming.** The core server now owns all artifact naming and storage. Plugins/workers never decide final filenames on the server. On upload, artifacts are stored into `data/jobs/{job_id}/artifacts/{kind}/` with deterministic names: `{prefix}_{plugin}_{task_type}_{variant:03d}_{hash8}_{timestamp}.{ext}`. A sidecar JSON is written next to each artifact with full provenance metadata. The upload endpoint now accepts multiple files with a parallel `artifacts_manifest` JSON field carrying kind, filename_hint, and per-artifact metadata.

**Pipeline input selectors.** Pipeline steps now use an `input_selector` field to control which upstream artifacts feed into downstream tasks. The selector supports `kind` filtering (image, video, any) and `pick` mode (first, all). Template variables available in `param_template` include both singular (`{artifact_id}`, `{artifact_path}`, `{artifact_kind}`) and plural (`{artifact_ids}`, `{artifact_paths}`) forms.
