"""Pipeline dependency resolution -- triggers downstream tasks on completion."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import Database
from app.schemas import ArtifactRecord, InputSelector, JobRecord, JobSpec, PipelineStep, TaskRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _resolve_template(template: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    """Replace {variable} placeholders in template values."""
    resolved = {}
    for key, value in template.items():
        if isinstance(value, str):
            for var_name, var_value in variables.items():
                value = value.replace(f"{{{var_name}}}", str(var_value) if not isinstance(var_value, str) else var_value)
        resolved[key] = value
    return resolved


def select_artifacts(
    artifacts: list[ArtifactRecord], selector: InputSelector
) -> list[ArtifactRecord]:
    """Filter and pick artifacts according to an InputSelector."""
    # Filter by kind
    if selector.kind != "any":
        artifacts = [a for a in artifacts if a.kind == selector.kind]

    # Stable ordering: by created_at then id
    artifacts = sorted(artifacts, key=lambda a: (a.created_at, a.id))

    # Pick
    if selector.pick == "first" and artifacts:
        return [artifacts[0]]
    return artifacts


def _build_template_variables(selected: list[ArtifactRecord]) -> dict[str, str]:
    """Build template variables from selected artifacts."""
    variables: dict[str, str] = {}
    if selected:
        # Singular (always the first)
        variables["artifact_id"] = selected[0].id
        variables["artifact_path"] = selected[0].filepath
        variables["artifact_kind"] = selected[0].kind
    # Plural (always available)
    variables["artifact_ids"] = json.dumps([a.id for a in selected])
    variables["artifact_paths"] = json.dumps([a.filepath for a in selected])
    return variables


class PipelineResolver:
    def __init__(self, db: Database):
        self.db = db

    async def check_pipelines(self, completed_task: TaskRecord, job_record: JobRecord) -> list[TaskRecord]:
        """Called when a task completes. Creates downstream tasks if pipeline steps match."""
        if not completed_task.ref_id:
            return []

        spec = JobSpec.model_validate_json(job_record.spec_json)
        created: list[TaskRecord] = []

        for step in spec.pipelines:
            if step.source_ref != completed_task.ref_id:
                continue
            if step.trigger_mode == "each":
                created.extend(await self._trigger_each(step, completed_task, job_record))
            elif step.trigger_mode == "all":
                created.extend(await self._trigger_all(step, completed_task, job_record))

        return created

    async def _trigger_each(self, step: PipelineStep, completed_task: TaskRecord, job_record: JobRecord) -> list[TaskRecord]:
        """Create downstream tasks for a single completed upstream task."""
        artifacts = await self.db.get_artifacts(task_id=completed_task.id)
        selected = select_artifacts(artifacts, step.input_selector)

        if not selected:
            return []

        variables = _build_template_variables(selected)
        params = _resolve_template(step.param_template, variables)

        created = []
        for _ in range(step.outputs_per_input):
            task_id = _uuid()
            now = _now()
            task = TaskRecord(
                id=task_id, job_id=job_record.id, plugin=step.plugin,
                task_type=step.task_type, payload_json=json.dumps(params),
                status="queued", created_at=now, updated_at=now,
            )
            await self.db.insert_task(task)
            created.append(task)
        return created

    async def _trigger_all(self, step: PipelineStep, completed_task: TaskRecord, job_record: JobRecord) -> list[TaskRecord]:
        """Create downstream tasks only when ALL upstream tasks with matching ref_id are done."""
        all_ref_tasks = await self.db.get_tasks_by_ref_id(job_record.id, step.source_ref)
        if not all(t.status == "completed" for t in all_ref_tasks):
            return []

        # Gather all artifacts from all completed tasks
        all_artifacts: list[ArtifactRecord] = []
        for t in all_ref_tasks:
            artifacts = await self.db.get_artifacts(task_id=t.id)
            all_artifacts.extend(artifacts)

        selected = select_artifacts(all_artifacts, step.input_selector)

        if not selected:
            return []

        variables = _build_template_variables(selected)
        params = _resolve_template(step.param_template, variables)

        created = []
        for _ in range(step.outputs_per_input):
            task_id = _uuid()
            now = _now()
            task = TaskRecord(
                id=task_id, job_id=job_record.id, plugin=step.plugin,
                task_type=step.task_type, payload_json=json.dumps(params),
                status="queued", created_at=now, updated_at=now,
            )
            await self.db.insert_task(task)
            created.append(task)
        return created
