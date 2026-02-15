"""Remote worker that polls the VPS for tasks and executes plugin flows."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import socket
from pathlib import Path

import httpx

from app.schemas import FlowError, NeedsHumanError, SiteFlowBase

logger = logging.getLogger("noapi.worker")


class RemoteWorker:
    """Worker that polls a noapi server for tasks and executes plugin flows."""

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
        self.flow: SiteFlowBase | None = None
        self._running = False

    def _headers(self) -> dict[str, str]:
        return {"X-Worker-Key": self.worker_key}

    def _load_plugin(self) -> None:
        """Import and instantiate the plugin flow class."""
        module = importlib.import_module(f"plugins.{self.plugin_name}.flows")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SiteFlowBase)
                and attr is not SiteFlowBase
            ):
                self.flow = attr()
                logger.info("Loaded plugin flow: %s.%s", self.plugin_name, attr_name)
                return
        raise RuntimeError(
            f"No SiteFlowBase subclass found in plugins.{self.plugin_name}.flows"
        )

    def _load_manifest(self) -> dict:
        """Load the plugin's manifest.json."""
        manifest_path = Path(f"plugins/{self.plugin_name}/manifest.json")
        with open(manifest_path) as f:
            return json.load(f)

    async def register(self, client: httpx.AsyncClient) -> None:
        """Register this worker with the VPS server."""
        manifest = self._load_manifest()
        resp = await client.post(
            f"{self.server_url}/api/workers/register",
            json={
                "worker_id": self.worker_id,
                "hostname": socket.gethostname(),
                "plugin": self.plugin_name,
                "capabilities": {"headed": self.headed},
                "manifest_json": manifest,
            },
            headers=self._headers(),
        )
        resp.raise_for_status()
        logger.info("Registered with server as %s", self.worker_id)

    async def claim_task(self, client: httpx.AsyncClient) -> dict | None:
        """Try to claim a task from the server."""
        resp = await client.post(
            f"{self.server_url}/api/tasks/claim",
            json={"worker_id": self.worker_id, "plugin": self.plugin_name},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("task")

    async def _heartbeat_loop(self, client: httpx.AsyncClient, task_id: str) -> None:
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

    async def upload_artifacts(
        self, client: httpx.AsyncClient, job_id: str, task_id: str, paths: list[str]
    ) -> None:
        """Upload artifact files to the server."""
        for file_path in paths:
            p = Path(file_path)
            if not p.exists():
                logger.warning("Artifact not found, skipping: %s", file_path)
                continue
            with open(p, "rb") as f:
                files = {"file": (p.name, f)}
                resp = await client.post(
                    f"{self.server_url}/api/upload/{job_id}/{task_id}",
                    files=files,
                    headers=self._headers(),
                )
                resp.raise_for_status()
            logger.info("Uploaded artifact: %s", p.name)

    async def run(self) -> None:
        """Main worker loop."""
        self._load_plugin()
        self._running = True

        from app.workers.browser import create_persistent_context, screenshot_on_error

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
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

                    logger.info(
                        "Claimed task %s (type=%s)", task_id, task_data["task_type"]
                    )

                    hb_task = asyncio.create_task(
                        self._heartbeat_loop(client, task_id)
                    )

                    try:
                        # Check auth first
                        if await self.flow.detect_auth_required(page):
                            ss = await screenshot_on_error(
                                page, task_id, screenshot_dir
                            )
                            raise NeedsHumanError("Authentication required", ss)

                        # Execute the plugin flow
                        result = await self.flow.execute(page, payload, download_dir)

                        # Upload artifacts and screenshots
                        if result.artifact_paths:
                            await self.upload_artifacts(
                                client, job_id, task_id, result.artifact_paths
                            )
                        if result.screenshots:
                            await self.upload_artifacts(
                                client, job_id, task_id, result.screenshots
                            )

                        # Report completion
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/complete",
                            json={
                                "worker_id": self.worker_id,
                                "result_json": result.metadata,
                            },
                            headers=self._headers(),
                        )
                        logger.info("Completed task %s", task_id)

                    except NeedsHumanError as e:
                        logger.warning("Task %s needs human: %s", task_id, e.message)
                        screenshot = e.screenshot_path
                        if screenshot:
                            await self.upload_artifacts(
                                client, job_id, task_id, [screenshot]
                            )
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/fail",
                            json={
                                "worker_id": self.worker_id,
                                "error": e.message,
                                "needs_human": True,
                                "screenshot_path": screenshot,
                            },
                            headers=self._headers(),
                        )

                    except (FlowError, Exception) as e:
                        logger.error("Task %s failed: %s", task_id, str(e))
                        ss = await screenshot_on_error(page, task_id, screenshot_dir)
                        await self.upload_artifacts(client, job_id, task_id, [ss])
                        needs_human = isinstance(e, FlowError) and False
                        await client.post(
                            f"{self.server_url}/api/tasks/{task_id}/fail",
                            json={
                                "worker_id": self.worker_id,
                                "error": str(e),
                                "needs_human": needs_human,
                                "screenshot_path": ss,
                            },
                            headers=self._headers(),
                        )

                    finally:
                        hb_task.cancel()
                        try:
                            await hb_task
                        except asyncio.CancelledError:
                            pass

            finally:
                await context.close()
                await pw.stop()

    def stop(self) -> None:
        """Signal the worker to stop after the current task."""
        self._running = False
        logger.info("Worker stop requested")
