"""Auth helper -- opens browser for manual login: python -m app.cli.auth --plugin NAME"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


async def run_auth(plugin_name: str) -> None:
    from app.workers.browser import create_persistent_context

    manifest_path = Path(f"plugins/{plugin_name}/manifest.json")
    if not manifest_path.exists():
        print(f"Error: Plugin manifest not found at {manifest_path}")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    auth_url = manifest.get("auth_url", "")
    print(f"Plugin: {manifest.get('display_name', plugin_name)}")
    print(f"Opening browser for manual login to: {auth_url}")
    print("Log in manually, then close the browser window or press Ctrl+C.")
    print()

    context, pw = await create_persistent_context(plugin_name, headed=True)
    page = await context.new_page()

    if auth_url:
        await page.goto(auth_url)

    try:
        # Wait for the page to close (user closes browser)
        await page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    finally:
        await context.close()
        await pw.stop()

    print("Session saved. You can now start a worker with this plugin.")


def main() -> None:
    parser = argparse.ArgumentParser(description="noapi auth helper")
    parser.add_argument("--plugin", required=True, help="Plugin name")
    args = parser.parse_args()
    asyncio.run(run_auth(args.plugin))


if __name__ == "__main__":
    main()
