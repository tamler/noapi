# noapi — Prompt 1b: Schema Improvements (APPLIED)

Status: COMPLETED — applied on top of Prompt 1 core build.

You are an expert automation engineer. You are working on an existing codebase/spec for **noapi** (generic browser automation service with FastAPI + SQLite + Playwright workers + plugins). Implement the following CHANGES ONLY. Do not redesign unrelated parts.

Goal: incorporate three improvements:
1) plugins return explicit artifact objects (not bare file paths)
2) the CORE owns artifact naming and storage (plugins never decide final filenames)
3) pipelines use stable artifact selectors, not a single {artifact_path} string

────────────────────────────────────────────────────────────
1) CHANGE: FlowResult must return Artifact objects
────────────────────────────────────────────────────────────

Current problem: FlowResult returns list[str] artifact_paths, which is ambiguous (multiple kinds, naming, screenshots, etc).

Implement these shared types in app/schemas.py and update plugins/workers accordingly:

- ArtifactSpec:
  - kind: "image"|"video"|"screenshot"|"other"
  - local_path: str                 # path on the WORKER machine
  - filename_hint: str | None       # optional suggested name (e.g. "upscale_1.png")
  - metadata: dict                  # plugin-specific per-artifact metadata

- FlowResult:
  - success: bool
  - artifacts: list[ArtifactSpec]   # ALL outputs including screenshots if desired
  - metadata: dict                  # plugin-specific task metadata
  - (optional) screenshots: list[ArtifactSpec] convenience, but not required

Update plugin base class signature:
- execute(...) returns FlowResult with artifacts, not paths.

Update worker:
- uploads the ArtifactSpec.local_path files (and preserves kind + metadata in upload request)
- does not assume file kinds by extension (kind comes from ArtifactSpec)

────────────────────────────────────────────────────────────
2) CHANGE: Core owns artifact naming + storage
────────────────────────────────────────────────────────────

Current problem: plugins naming outputs causes inconsistency and makes storage/indexing messy.

Implement server-side storage rules:
- Worker uploads artifacts via POST /api/upload/{job_id}/{task_id} multipart.
- Each file part must include metadata: kind + filename_hint + per-artifact metadata.
  (Implement as: multipart files[] + a parallel JSON field "artifacts_manifest" listing each file with kind + metadata keyed by original filename.)

On the SERVER:
- Store artifacts into: data/jobs/{job_id}/artifacts/{kind}/
- Rename deterministically:
  {prefix}_{plugin}_{task_type}_{variant:03d}_{hash8}_{YYYYMMDD_HHMMSS}.{ext}
  Where:
   - prefix = job.naming_prefix if set else job_id
   - variant is derived from task payload (variant_index) or 0 if absent
   - hash8 = first 8 of sha256 of stored file bytes
   - ext derived from original filename
- Write sidecar JSON next to each stored artifact (same basename + .json) including:
  - job_id, task_id, plugin, task_type, created_at
  - FlowResult.metadata (task-level)
  - ArtifactSpec.metadata (artifact-level)
  - original_filename, kind, sha256, file_size_bytes, is_duplicate

Duplicate logic:
- If sha256 repeats within the same job_id, mark is_duplicate=true for later entries.

IMPORTANT:
- Plugins/worker should NEVER decide the final stored filename on the server.
- filename_hint is only informational and goes into metadata, not necessarily used for naming.

────────────────────────────────────────────────────────────
3) CHANGE: Pipeline steps must use input selectors
────────────────────────────────────────────────────────────

Current problem: pipelines referencing a single {artifact_path} is brittle.

Update PipelineStep schema:
- source_ref: str
- input_selector:
    kind: "image"|"video"|"any" (default "any")
    pick: "first"|"all"         (v1 only)
- trigger_mode: "each"|"all"
- plugin, task_type, param_template, outputs_per_input, etc remain.

Pipeline resolution logic on SERVER:
- When an upstream task completes:
  - If trigger_mode="each":
     select inputs from THAT task's artifacts (filter by kind, then pick)
     create downstream task(s)
     provide template variables to param_template:
       - singular: {artifact_id}, {artifact_path}, {artifact_kind}
       - if pick="all": {artifact_ids}, {artifact_paths}
  - If trigger_mode="all":
     wait until ALL tasks sharing source_ref are completed
     select inputs across ALL their artifacts (filter by kind, then pick)
     provide template variables:
       - {artifact_ids} / {artifact_paths} lists
       - and singular versions if pick="first"

Notes:
- Implement stable ordering for "first" (e.g., by artifacts.created_at then artifacts.id).
- v1 does NOT need best/latest selection, but the schema must be extendable later.

────────────────────────────────────────────────────────────
4) Update example plugin + docs
────────────────────────────────────────────────────────────

- Update plugins/_example/flows.py to return FlowResult with ArtifactSpec objects.
- Update example job spec to include a pipeline step using input_selector with pick="all" and trigger_mode="all".
- Update README to explain artifact objects, server-owned naming, pipeline selectors.

────────────────────────────────────────────────────────────
5) Deliverables
────────────────────────────────────────────────────────────

- Code changes implementing the above with minimal disruption.
- Migrations (if needed) for SQLite schema, or auto-create new tables/columns if missing.
- A short CHANGELOG section in README describing these updates.
- Tests: unit test for deterministic naming function + unit test for pipeline selection (first vs all).
