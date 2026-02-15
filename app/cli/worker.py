"""Start a noapi worker: python -m app.cli.worker --server URL --plugin NAME --worker-id ID"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal


def main() -> None:
    parser = argparse.ArgumentParser(description="noapi worker")
    parser.add_argument("--server", required=True, help="VPS server URL")
    parser.add_argument("--plugin", required=True, help="Plugin name to load")
    parser.add_argument("--worker-id", required=True, help="Unique worker identifier")
    parser.add_argument(
        "--headed", action="store_true", default=False, help="Run browser in headed mode"
    )
    parser.add_argument(
        "--headless", action="store_true", help="Run browser headless (default)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Poll interval in seconds (default: 5)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from app.workers.remote_worker import RemoteWorker

    headed = args.headed and not args.headless
    worker = RemoteWorker(
        server_url=args.server,
        plugin_name=args.plugin,
        worker_id=args.worker_id,
        worker_key=os.getenv("NOAPI_WORKER_KEY", ""),
        headed=headed,
        poll_interval=args.poll_interval,
    )

    # Handle graceful shutdown
    def handle_signal(sig, frame):
        logging.getLogger("noapi.worker").info("Received signal %s, stopping...", sig)
        worker.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
