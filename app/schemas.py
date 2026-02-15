"""Pydantic schemas and plugin base classes for noapi."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Plugin base classes (plain Python, not Pydantic)
# ---------------------------------------------------------------------------

@dataclass
class FlowResult:
    success: bool
    artifact_paths: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)


class NeedsHumanError(Exception):
    def __init__(self, message: str, screenshot_path: str | None = None):
        super().__init__(message)
        self.message = message
        self.screenshot_path = screenshot_path


class FlowError(Exception):
    def __init__(self, message: str, screenshot_path: str | None = None):
        super().__init__(message)
        self.message = message
        self.screenshot_path = screenshot_path


@dataclass
class HealthCheckResult:
    healthy: bool
    selectors_found: list[str] = field(default_factory=list)
    selectors_missing: list[str] = field(default_factory=list)
    message: str = ""


class SiteFlowBase(ABC):
    @abstractmethod
    async def execute(self, page, task_payload: dict, download_dir: str) -> FlowResult:
        pass

    @abstractmethod
    async def detect_auth_required(self, page) -> bool:
        pass

    @abstractmethod
    async def health_check(self, page) -> HealthCheckResult:
        pass


# ---------------------------------------------------------------------------
# Job spec models
# ---------------------------------------------------------------------------

class TaskSpec(BaseModel):
    plugin: str
    task_type: str
    params: dict[str, Any]
    depends_on: str | None = None
    ref_id: str | None = None


class VariantExpansion(BaseModel):
    plugin: str
    task_type: str
    param_template: dict[str, Any]
    expand_over: dict[str, list[Any]]
    variants: int = 1
    depends_on: str | None = None
    ref_id: str | None = None


class PipelineStep(BaseModel):
    source_ref: str
    plugin: str
    task_type: str
    param_template: dict[str, Any]
    outputs_per_input: int = 1
    trigger_mode: str = "each"


class JobSpec(BaseModel):
    project_name: str
    description: str | None = None
    tasks: list[TaskSpec] = []
    expansions: list[VariantExpansion] = []
    pipelines: list[PipelineStep] = []
    global_params: dict[str, Any] = {}
    naming_prefix: str | None = None


# ---------------------------------------------------------------------------
# Database record models
# ---------------------------------------------------------------------------

class TaskRecord(BaseModel):
    id: str
    job_id: str
    plugin: str
    task_type: str
    payload_json: str
    status: str = "queued"
    depends_on_task_id: str | None = None
    ref_id: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
    assigned_worker_id: str | None = None
    created_at: str
    updated_at: str
    heartbeat_at: str | None = None


class ArtifactRecord(BaseModel):
    id: str
    job_id: str
    task_id: str
    plugin: str
    kind: str
    filepath: str
    original_filename: str | None = None
    sha256: str | None = None
    file_size_bytes: int | None = None
    is_duplicate: bool = False
    metadata_json: str | None = None
    created_at: str


class JobRecord(BaseModel):
    id: str
    project_name: str | None = None
    spec_json: str
    status: str = "active"
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    created_at: str
    updated_at: str


class WorkerRecord(BaseModel):
    worker_id: str
    hostname: str | None = None
    plugin: str | None = None
    capabilities_json: str | None = None
    last_seen_at: str | None = None
    registered_at: str


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

class ClaimRequest(BaseModel):
    worker_id: str
    plugin: str


class HeartbeatRequest(BaseModel):
    worker_id: str


class CompleteRequest(BaseModel):
    worker_id: str
    result_json: dict[str, Any] = {}


class FailRequest(BaseModel):
    worker_id: str
    error: str
    needs_human: bool = False
    screenshot_path: str | None = None


class WorkerRegisterRequest(BaseModel):
    worker_id: str
    hostname: str | None = None
    plugin: str
    capabilities: dict[str, Any] = {}
    manifest_json: dict | None = None
