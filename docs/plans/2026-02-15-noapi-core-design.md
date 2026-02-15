# noapi Core Service Design

## Summary

noapi is a site-agnostic browser automation service that turns UI-only websites into programmable, queue-based automation systems. The core handles queueing, workers, artifact storage, human intervention, and a dashboard. All site-specific logic lives in plugins.

## Architecture

- **VPS (Core)**: FastAPI + SQLite queue + artifact store + static SPA dashboard
- **Workers (Remote)**: Playwright-based, poll VPS for tasks, execute plugin flows, upload artifacts back
- **Plugins**: Python packages under `plugins/` with manifest, selectors, flows, errors

## Tech Stack

Python 3.11+, FastAPI, SQLite (aiosqlite), Playwright (Python), Pydantic v2, httpx (workers), uvicorn.

## Key Decisions

### Pipeline Behavior

`PipelineStep.trigger_mode` controls downstream task creation:
- `"each"` (default): Each upstream task completion immediately creates downstream task(s). `{artifact_path}` resolves to the completing task's artifact.
- `"all"`: Wait for ALL tasks with the `source_ref` to complete. `{artifact_paths}` (plural) available as JSON list. Then create downstream tasks.
- Both modes multiply by `outputs_per_input`.

### Dashboard

Single-page app. `index.html` + `app.js` + `styles.css` served as static files. Hash-based tabs: Jobs | Workers | Plugins. Job detail is drill-down within Jobs tab. Polls every 3s. No build step, no framework.

### Auth

- Worker endpoints: `X-Worker-Key` header checked against `NOAPI_WORKER_KEY` env var
- Dashboard: Optional HTTP Basic Auth via `NOAPI_BASIC_AUTH` env var
- Target site auth: Playwright persistent browser sessions on worker machines

### Database Access

aiosqlite for async SQLite from FastAPI async endpoints.

### Stale Task Recovery

FastAPI lifespan background task checks for running tasks with heartbeat_at > 2 minutes old. Requeues if attempts < max_attempts, else fails.

## File Structure

~20 Python modules, 3 static files, 1 example plugin template, supporting config files. See spec for full tree.
