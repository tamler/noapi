import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from app.db import Database
from app.schemas import (
    ArtifactRecord, InputSelector, JobRecord, JobSpec, PipelineStep, TaskRecord, TaskSpec,
)
from app.services.pipeline import PipelineResolver, select_artifacts


def _now():
    return datetime.now(timezone.utc).isoformat()

@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.init()
    yield database
    await database.close()

def _make_job_with_pipeline(trigger_mode="each", input_selector=None):
    if input_selector is None:
        # Default: "each" picks first artifact, "all" picks all artifacts
        pick = "all" if trigger_mode == "all" else "first"
        input_selector = InputSelector(pick=pick)
    spec = JobSpec(
        project_name="test",
        tasks=[TaskSpec(plugin="ex", task_type="gen", params={"prompt": "hi"}, ref_id="imgs")],
        pipelines=[PipelineStep(
            source_ref="imgs", plugin="ex", task_type="upscale",
            param_template={"input": "{artifact_path}" if trigger_mode == "each" else "{artifact_paths}"},
            input_selector=input_selector,
            trigger_mode=trigger_mode,
            outputs_per_input=1,
        )],
    )
    job = JobRecord(id="job1", spec_json=spec.model_dump_json(), created_at=_now(), updated_at=_now())
    return job

@pytest.mark.asyncio
async def test_each_mode_creates_on_completion(db):
    job = _make_job_with_pipeline("each")
    await db.insert_job(job)
    task = TaskRecord(id="t1", job_id="job1", plugin="ex", task_type="gen",
                      payload_json="{}", status="completed", ref_id="imgs",
                      created_at=_now(), updated_at=_now())
    await db.insert_task(task)
    art = ArtifactRecord(id="a1", job_id="job1", task_id="t1", plugin="ex",
                         kind="image", filepath="/tmp/img.png", created_at=_now())
    await db.insert_artifact(art)

    resolver = PipelineResolver(db)
    created = await resolver.check_pipelines(task, job)
    assert len(created) == 1
    payload = json.loads(created[0].payload_json)
    assert payload["input"] == "/tmp/img.png"
    assert created[0].status == "queued"

@pytest.mark.asyncio
async def test_all_mode_waits_for_all(db):
    job = _make_job_with_pipeline("all")
    await db.insert_job(job)
    t1 = TaskRecord(id="t1", job_id="job1", plugin="ex", task_type="gen",
                    payload_json="{}", status="completed", ref_id="imgs",
                    created_at=_now(), updated_at=_now())
    t2 = TaskRecord(id="t2", job_id="job1", plugin="ex", task_type="gen",
                    payload_json="{}", status="running", ref_id="imgs",
                    created_at=_now(), updated_at=_now())
    await db.insert_task(t1)
    await db.insert_task(t2)
    await db.insert_artifact(ArtifactRecord(id="a1", job_id="job1", task_id="t1",
                                            plugin="ex", kind="image", filepath="/a.png", created_at=_now()))

    resolver = PipelineResolver(db)
    # First completion -- t2 still running, should not trigger
    created = await resolver.check_pipelines(t1, job)
    assert len(created) == 0

    # Complete t2
    await db.update_task("t2", status="completed")
    await db.insert_artifact(ArtifactRecord(id="a2", job_id="job1", task_id="t2",
                                            plugin="ex", kind="image", filepath="/b.png", created_at=_now()))
    t2_completed = await db.get_task("t2")
    created = await resolver.check_pipelines(t2_completed, job)
    assert len(created) == 1
    payload = json.loads(created[0].payload_json)
    paths = json.loads(payload["input"])
    assert set(paths) == {"/a.png", "/b.png"}

@pytest.mark.asyncio
async def test_outputs_per_input(db):
    spec = JobSpec(
        project_name="test",
        tasks=[TaskSpec(plugin="ex", task_type="gen", params={}, ref_id="imgs")],
        pipelines=[PipelineStep(
            source_ref="imgs", plugin="ex", task_type="upscale",
            param_template={"input": "{artifact_path}"},
            trigger_mode="each", outputs_per_input=3,
        )],
    )
    job = JobRecord(id="job1", spec_json=spec.model_dump_json(), created_at=_now(), updated_at=_now())
    await db.insert_job(job)
    task = TaskRecord(id="t1", job_id="job1", plugin="ex", task_type="gen",
                      payload_json="{}", status="completed", ref_id="imgs",
                      created_at=_now(), updated_at=_now())
    await db.insert_task(task)
    await db.insert_artifact(ArtifactRecord(id="a1", job_id="job1", task_id="t1",
                                            plugin="ex", kind="image", filepath="/x.png", created_at=_now()))
    resolver = PipelineResolver(db)
    created = await resolver.check_pipelines(task, job)
    assert len(created) == 3

@pytest.mark.asyncio
async def test_no_pipelines_noop(db):
    spec = JobSpec(project_name="test")
    job = JobRecord(id="job1", spec_json=spec.model_dump_json(), created_at=_now(), updated_at=_now())
    await db.insert_job(job)
    task = TaskRecord(id="t1", job_id="job1", plugin="ex", task_type="gen",
                      payload_json="{}", status="completed", ref_id="imgs",
                      created_at=_now(), updated_at=_now())
    await db.insert_task(task)
    resolver = PipelineResolver(db)
    created = await resolver.check_pipelines(task, job)
    assert len(created) == 0


# --- New tests for input selector ---

def test_select_artifacts_kind_filter():
    """InputSelector filters by kind."""
    arts = [
        ArtifactRecord(id="a1", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/img.png", created_at="2026-01-01T00:00:00"),
        ArtifactRecord(id="a2", job_id="j", task_id="t", plugin="p",
                       kind="screenshot", filepath="/ss.png", created_at="2026-01-01T00:00:01"),
        ArtifactRecord(id="a3", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/img2.png", created_at="2026-01-01T00:00:02"),
    ]
    # Filter for images only
    sel = InputSelector(kind="image", pick="all")
    result = select_artifacts(arts, sel)
    assert len(result) == 2
    assert all(a.kind == "image" for a in result)

    # Filter for screenshots
    sel = InputSelector(kind="screenshot", pick="all")
    result = select_artifacts(arts, sel)
    assert len(result) == 1
    assert result[0].id == "a2"


def test_select_artifacts_pick_first():
    """InputSelector pick='first' returns only the first artifact."""
    arts = [
        ArtifactRecord(id="a1", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/img1.png", created_at="2026-01-01T00:00:02"),
        ArtifactRecord(id="a2", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/img2.png", created_at="2026-01-01T00:00:01"),
    ]
    sel = InputSelector(kind="any", pick="first")
    result = select_artifacts(arts, sel)
    assert len(result) == 1
    # Should pick a2 (earlier created_at)
    assert result[0].id == "a2"


def test_select_artifacts_pick_all():
    """InputSelector pick='all' returns all matching artifacts in stable order."""
    arts = [
        ArtifactRecord(id="a3", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/3.png", created_at="2026-01-01T00:00:03"),
        ArtifactRecord(id="a1", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/1.png", created_at="2026-01-01T00:00:01"),
        ArtifactRecord(id="a2", job_id="j", task_id="t", plugin="p",
                       kind="image", filepath="/2.png", created_at="2026-01-01T00:00:02"),
    ]
    sel = InputSelector(kind="any", pick="all")
    result = select_artifacts(arts, sel)
    assert len(result) == 3
    # Stable ordering: by created_at then id
    assert [a.id for a in result] == ["a1", "a2", "a3"]


def test_select_artifacts_no_match():
    """InputSelector returns empty when no artifacts match kind."""
    arts = [
        ArtifactRecord(id="a1", job_id="j", task_id="t", plugin="p",
                       kind="screenshot", filepath="/ss.png", created_at="2026-01-01T00:00:00"),
    ]
    sel = InputSelector(kind="video", pick="all")
    result = select_artifacts(arts, sel)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_each_mode_with_kind_filter(db):
    """Pipeline with input_selector kind filter skips non-matching artifacts."""
    selector = InputSelector(kind="image", pick="first")
    job = _make_job_with_pipeline("each", input_selector=selector)
    await db.insert_job(job)
    task = TaskRecord(id="t1", job_id="job1", plugin="ex", task_type="gen",
                      payload_json="{}", status="completed", ref_id="imgs",
                      created_at=_now(), updated_at=_now())
    await db.insert_task(task)
    # Insert a screenshot first, then an image
    await db.insert_artifact(ArtifactRecord(id="ss1", job_id="job1", task_id="t1",
                                            plugin="ex", kind="screenshot", filepath="/ss.png",
                                            created_at="2026-01-01T00:00:00"))
    await db.insert_artifact(ArtifactRecord(id="img1", job_id="job1", task_id="t1",
                                            plugin="ex", kind="image", filepath="/img.png",
                                            created_at="2026-01-01T00:00:01"))

    resolver = PipelineResolver(db)
    created = await resolver.check_pipelines(task, job)
    assert len(created) == 1
    payload = json.loads(created[0].payload_json)
    # Should use the image, not the screenshot
    assert payload["input"] == "/img.png"
