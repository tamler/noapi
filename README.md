# noapi

A site-agnostic browser automation service that turns UI-only websites into programmable, queue-based automation systems. Define what you want done in a JSON job spec, and remote Playwright workers execute the browser flows, uploading artifacts back to a central server. All site-specific logic lives in plugins.

## Architecture

```
VPS (Core)
+-----------------------------------------------+
|  FastAPI --- SQLite Queue --- Artifact Store    |
|     |                                          |
|  Dashboard (static HTML+JS)                    |
+------------------+----------------------------+
                   | HTTP (poll/claim/upload)
        +----------+----------+
        v          v          v
     Worker 1   Worker 2   Worker N
     (Playwright on any machine)
```

- **Core server** runs on a VPS: receives job specs, queues tasks, stores artifacts, serves a dashboard.
- **Workers** run anywhere with a browser: poll the server for tasks, execute plugin-defined browser flows, upload results back.
- **Plugins** are Python packages under `plugins/` that define selectors, flows, and error detection for a specific site.

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Start the server

```bash
python -m app.cli.server
```

The server starts on `http://localhost:8000` by default. The dashboard is available at the root URL.

### 3. Save a browser session (one-time per plugin)

```bash
python -m app.cli.auth --plugin example_service
```

A headed browser opens. Log in to the target site manually, then close the browser. The session is saved for the worker to reuse.

### 4. Start a worker

```bash
python -m app.cli.worker \
  --server http://localhost:8000 \
  --plugin example_service \
  --worker-id worker-1 \
  --headed
```

The worker registers with the server, uploads the plugin manifest, and begins polling for tasks.

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

## Job Specs

A job spec is a JSON document that describes what work to do. It supports three ways to define tasks:

### Explicit tasks

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

This creates `2 subjects * 2 ratios * 2 variants = 8` tasks. The `global_params` are merged into each task's parameters.

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
      "trigger_mode": "each",
      "outputs_per_input": 1
    }
  ]
}
```

- `trigger_mode: "each"` -- create downstream tasks as each upstream task completes. `{artifact_path}` resolves to the completing task's artifact.
- `trigger_mode: "all"` -- wait for all upstream tasks with the `source_ref` to complete, then create downstream tasks. `{artifact_paths}` (plural) is available as a JSON list.

See [`examples/job_example.json`](examples/job_example.json) for a complete example.

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

The flow class must inherit from `SiteFlowBase` and implement `execute()`, `detect_auth_required()`, and `health_check()`.

See [`plugins/_example/README.md`](plugins/_example/README.md) for a step-by-step guide.

## API Reference

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Server health check (DB connectivity, disk space) |
| `GET` | `/api/health/selectors` | Selector health check for a plugin (`?plugin=name`) |

### Jobs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Submit a job spec (JSON body) |
| `GET` | `/api/jobs` | List all jobs with summary counts |
| `GET` | `/api/jobs/{job_id}` | Get job detail with task breakdown by status |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel all queued/blocked tasks in a job |

### Tasks

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tasks` | List tasks (`?job_id=`, `?status=`, `?plugin=`) |
| `POST` | `/api/tasks/claim` | Atomically claim a queued task (worker endpoint) |
| `POST` | `/api/tasks/{task_id}/heartbeat` | Worker heartbeat to prevent stale-task recovery |
| `POST` | `/api/tasks/{task_id}/complete` | Mark task completed, triggers pipeline resolution |
| `POST` | `/api/tasks/{task_id}/fail` | Mark task failed or needs_human |
| `POST` | `/api/tasks/{task_id}/retry` | Reset a needs_human task back to queued |

### Artifacts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/artifacts` | List artifacts (`?job_id=`, `?task_id=`, `?kind=`) |
| `GET` | `/api/artifacts/{artifact_id}/download` | Download an artifact file |
| `POST` | `/api/upload/{job_id}/{task_id}` | Upload artifact files (worker endpoint, multipart) |

### Workers

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/workers/register` | Register a worker and upload plugin manifest |
| `GET` | `/api/workers` | List registered workers |

### Plugins

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/plugins` | List all registered plugin manifests |
| `GET` | `/api/plugins/{name}` | Get a specific plugin manifest |

## Dashboard

The built-in dashboard is a single-page application served at the root URL. It provides:

- **Jobs tab** -- Submit job specs, view job list with progress bars, drill into job details with task breakdowns by status, view artifacts in a grid layout.
- **Workers tab** -- Monitor worker status, see which plugin each worker handles, track online/stale status based on heartbeat.
- **Plugins tab** -- Browse registered plugin manifests and their capabilities.
- **Needs Human** -- Jobs with tasks requiring human intervention are highlighted. Screenshots and error messages are displayed with a retry button.

The dashboard polls the API every 3 seconds for live updates.

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

## Security

- **Worker authentication** -- Set `NOAPI_WORKER_KEY` to a shared secret. Workers must include it in the `X-Worker-Key` header. All worker endpoints (claim, heartbeat, complete, fail, upload, register) are protected.
- **Dashboard authentication** -- Set `NOAPI_BASIC_AUTH` to `user:password` to require HTTP Basic Auth for the dashboard and job management endpoints.
- **Browser sessions** -- Playwright persistent sessions are stored locally on each worker machine (never uploaded to the server). Each plugin gets its own session directory.
- **TLS** -- Use a reverse proxy (Caddy, nginx) to terminate TLS. The server itself runs plain HTTP on localhost.
