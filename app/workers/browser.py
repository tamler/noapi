"""Playwright browser context and helper utilities for workers."""
from __future__ import annotations

import os
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

WORKER_SESSION_ROOT = Path(os.getenv("WORKER_SESSION_ROOT", "./sessions"))


async def create_persistent_context(
    plugin_name: str,
    headed: bool = True,
) -> tuple[BrowserContext, object]:
    """
    Create a Playwright persistent browser context.

    Session data is stored in WORKER_SESSION_ROOT/{plugin_name}/.
    Returns (context, playwright_instance). Caller must close both.
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
    """Take a full-page screenshot and return the file path."""
    path = Path(screenshot_dir) / f"{task_id}_error.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(path), full_page=True)
    return str(path)


async def wait_with_timeout(page: Page, selector: str, timeout_ms: int = 30000) -> None:
    """Wait for a selector with a clear error message on timeout."""
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
    except Exception:
        raise TimeoutError(f"Selector '{selector}' not found within {timeout_ms}ms")


async def download_artifact(page: Page, download_trigger, download_dir: str) -> str:
    """
    Execute a download trigger action and wait for the download.

    Args:
        page: Playwright page
        download_trigger: Async callable that triggers the download (e.g., clicking a button)
        download_dir: Directory to save the downloaded file

    Returns:
        Path to the downloaded file.
    """
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    async with page.expect_download() as download_info:
        await download_trigger()
    download = await download_info.value
    dest = download_path / download.suggested_filename
    await download.save_as(str(dest))
    return str(dest)
