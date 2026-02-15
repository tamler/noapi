"""FastAPI application shell with auth middleware, lifespan, and stale task recovery."""
from __future__ import annotations

import asyncio
import base64
import logging
import secrets

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.plugin_registry import PluginRegistry
from app.settings import settings

logger = logging.getLogger("noapi")

# Module-level singletons -- imported by route modules
db = Database(settings.db_path)
registry = PluginRegistry()


async def _stale_task_loop() -> None:
    """Background loop: recover stale running tasks every 60 seconds."""
    while True:
        try:
            await asyncio.sleep(60)
            stale = await db.get_stale_tasks(timeout_seconds=120)
            for task in stale:
                logger.warning("Recovering stale task %s (worker=%s)", task.id, task.assigned_worker_id)
                if task.attempts + 1 < task.max_attempts:
                    await db.update_task(
                        task.id,
                        status="queued",
                        assigned_worker_id=None,
                        heartbeat_at=None,
                        attempts=task.attempts + 1,
                    )
                else:
                    await db.update_task(
                        task.id,
                        status="failed",
                        last_error="Stale task: heartbeat timeout",
                    )
                await db.update_job_counts(task.job_id)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in stale task recovery loop")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB, ensure dirs, start background tasks."""
    settings.ensure_dirs()
    await db.init()
    logger.info("Database initialized at %s", settings.db_path)

    stale_task = asyncio.create_task(_stale_task_loop())
    try:
        yield
    finally:
        stale_task.cancel()
        try:
            await stale_task
        except asyncio.CancelledError:
            pass
        await db.close()
        logger.info("Database closed")


app = FastAPI(
    title="noapi",
    description="Headless browser automation queue",
    root_path=settings.root_path,
    lifespan=lifespan,
)

# CORS middleware
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Auth middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next) -> Response:
    """Enforce worker key for worker endpoints, optional basic auth for dashboard."""
    path = request.url.path
    method = request.method

    # Health endpoint is always public
    if path.startswith("/api/health"):
        return await call_next(request)

    # Static assets and dashboard root are public
    if path == "/" or path.startswith("/static"):
        return await call_next(request)

    # Determine if this is a worker endpoint
    is_worker_endpoint = (
        path.startswith("/api/workers")
        or path.startswith("/api/tasks/claim")
        or path.startswith("/api/upload")
        or (method == "POST" and path.startswith("/api/tasks/"))
    )

    # GET /api/plugins is accessible without worker key (dashboard needs it)
    is_public_get = method == "GET" and path.startswith("/api/plugins")

    if is_worker_endpoint and not is_public_get:
        # Require worker key
        if settings.worker_key:
            provided = request.headers.get("X-Worker-Key", "")
            if not secrets.compare_digest(provided, settings.worker_key):
                return Response(
                    content='{"detail":"Invalid or missing worker key"}',
                    status_code=403,
                    media_type="application/json",
                )
    else:
        # Dashboard/job routes: optional basic auth
        if settings.basic_auth:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Basic "):
                return Response(
                    content='{"detail":"Authentication required"}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": "Basic"},
                )
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            except Exception:
                return Response(
                    content='{"detail":"Invalid auth header"}',
                    status_code=401,
                    media_type="application/json",
                )
            if not secrets.compare_digest(decoded, settings.basic_auth):
                return Response(
                    content='{"detail":"Invalid credentials"}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": "Basic"},
                )

    return await call_next(request)


# Import and include routers (after app and singletons are created to avoid circular imports)
from app.routes import health, workers, plugins, tasks, artifacts, jobs  # noqa: E402

app.include_router(health.router)
app.include_router(workers.router)
app.include_router(plugins.router)
app.include_router(tasks.router)
app.include_router(artifacts.router)
app.include_router(jobs.router)

# Static file mount for dashboard assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def dashboard():
    """Serve the dashboard."""
    return FileResponse("app/static/index.html")
