"""Environment-based configuration for noapi."""

from __future__ import annotations

import os
from pathlib import Path


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        self.host: str = os.getenv("NOAPI_HOST", "0.0.0.0")
        self.port: int = int(os.getenv("NOAPI_PORT", "8000"))
        self.data_dir: Path = Path(os.getenv("NOAPI_DATA_DIR", "./data"))
        self.worker_key: str = os.getenv("NOAPI_WORKER_KEY", "")
        self.basic_auth: str = os.getenv("NOAPI_BASIC_AUTH", "")
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
