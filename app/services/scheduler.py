"""Job spec parsing and task creation."""
from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import Database
from app.plugin_registry import PluginRegistry
from app.schemas import (
    JobRecord, JobSpec, TaskRecord, TaskSpec, VariantExpansion,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def expand_variants(expansion: VariantExpansion, global_params: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of param dicts from cartesian product * variants."""
    keys = list(expansion.expand_over.keys())
    values = list(expansion.expand_over.values())
    result: list[dict[str, Any]] = []
    for combo in itertools.product(*values):
        params = {**global_params, **expansion.param_template}
        for key, val in zip(keys, combo):
            resolved: dict[str, Any] = {}
            for pk, pv in params.items():
                if isinstance(pv, str) and f"{{{key}}}" in pv:
                    resolved[pk] = pv.replace(f"{{{key}}}", str(val))
                else:
                    resolved[pk] = pv
            params = resolved
        for _ in range(expansion.variants):
            result.append(dict(params))
    return result


class Scheduler:
    def __init__(self, db: Database, registry: PluginRegistry):
        self.db = db
        self.registry = registry

    async def schedule_job(self, spec: JobSpec) -> JobRecord:
        """Parse job spec, validate against registry, create job + tasks in DB."""
        # 1. Validate all plugin/task_type references
        errors = self._validate_spec(spec)
        if errors:
            raise ValueError("Job spec validation failed:\n" + "\n".join(errors))

        # 2. Create job record
        job_id = _uuid()
        now = _now()
        job = JobRecord(
            id=job_id,
            project_name=spec.project_name,
            spec_json=spec.model_dump_json(),
            created_at=now,
            updated_at=now,
        )
        await self.db.insert_job(job)

        # Track ref_id -> list of task IDs for dependency resolution
        ref_to_task_ids: dict[str, list[str]] = {}
        task_count = 0

        # 3. Process explicit tasks
        for task_spec in spec.tasks:
            task_id = _uuid()
            merged_params = {**spec.global_params, **task_spec.params}
            depends_on = None
            status = "queued"
            if task_spec.depends_on and task_spec.depends_on in ref_to_task_ids:
                depends_on = ref_to_task_ids[task_spec.depends_on][0]
                status = "blocked"

            task = TaskRecord(
                id=task_id, job_id=job_id, plugin=task_spec.plugin,
                task_type=task_spec.task_type, payload_json=json.dumps(merged_params),
                status=status, depends_on_task_id=depends_on,
                ref_id=task_spec.ref_id, created_at=now, updated_at=now,
            )
            await self.db.insert_task(task)
            task_count += 1
            if task_spec.ref_id:
                ref_to_task_ids.setdefault(task_spec.ref_id, []).append(task_id)

        # 4. Process variant expansions
        for expansion in spec.expansions:
            param_list = expand_variants(expansion, spec.global_params)
            for params in param_list:
                task_id = _uuid()
                depends_on = None
                status = "queued"
                if expansion.depends_on and expansion.depends_on in ref_to_task_ids:
                    depends_on = ref_to_task_ids[expansion.depends_on][0]
                    status = "blocked"

                task = TaskRecord(
                    id=task_id, job_id=job_id, plugin=expansion.plugin,
                    task_type=expansion.task_type, payload_json=json.dumps(params),
                    status=status, depends_on_task_id=depends_on,
                    ref_id=expansion.ref_id, created_at=now, updated_at=now,
                )
                await self.db.insert_task(task)
                task_count += 1
                if expansion.ref_id:
                    ref_to_task_ids.setdefault(expansion.ref_id, []).append(task_id)

        # 5. Pipeline steps are stored in spec_json -- no tasks created at submission time

        # 6. Update job with task count
        await self.db.update_job(job_id, total_tasks=task_count, updated_at=_now())
        return await self.db.get_job(job_id)

    def _validate_spec(self, spec: JobSpec) -> list[str]:
        """Validate all plugin/task_type/param references against registry."""
        errors: list[str] = []
        for task_spec in spec.tasks:
            merged = {**spec.global_params, **task_spec.params}
            errors.extend(self.registry.validate_task(task_spec.plugin, task_spec.task_type, merged))
        for expansion in spec.expansions:
            # Only validate plugin/task_type existence; params have placeholders
            if not self.registry.has_plugin(expansion.plugin):
                errors.append(f"Unknown plugin: {expansion.plugin}")
            elif not self.registry.get_task_type(expansion.plugin, expansion.task_type):
                errors.append(f"Unknown task type '{expansion.task_type}' for plugin '{expansion.plugin}'")
        for pipeline in spec.pipelines:
            # Only validate plugin/task_type existence; params are templated
            if not self.registry.has_plugin(pipeline.plugin):
                errors.append(f"Unknown plugin: {pipeline.plugin}")
            elif not self.registry.get_task_type(pipeline.plugin, pipeline.task_type):
                errors.append(f"Unknown task type '{pipeline.task_type}' for plugin '{pipeline.plugin}'")
        return errors
