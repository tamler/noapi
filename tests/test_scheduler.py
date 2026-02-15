import json
import pytest
import pytest_asyncio
from app.db import Database
from app.plugin_registry import PluginRegistry
from app.schemas import JobSpec, TaskSpec, VariantExpansion, PipelineStep
from app.services.scheduler import Scheduler, expand_variants

MOCK_MANIFEST = {
    "name": "example",
    "display_name": "Example",
    "version": "0.1.0",
    "capabilities": {
        "task_types": [
            {
                "name": "generate_image",
                "params_schema": {
                    "prompt": {"type": "string", "required": True},
                    "aspect_ratio": {"type": "string", "required": False, "default": "1:1",
                                     "enum": ["1:1", "16:9", "9:16"]},
                },
                "artifact_kind": "image",
            },
            {
                "name": "upscale_image",
                "params_schema": {
                    "input_image": {"type": "string", "required": True},
                },
                "artifact_kind": "image",
            },
        ],
    },
}

@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.init()
    yield database
    await database.close()

@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.register(MOCK_MANIFEST)
    return reg

@pytest.mark.asyncio
async def test_schedule_explicit_tasks(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(project_name="test", tasks=[
        TaskSpec(plugin="example", task_type="generate_image", params={"prompt": "hello"})
    ])
    job = await scheduler.schedule_job(spec)
    tasks = await db.get_tasks(job_id=job.id)
    assert len(tasks) == 1
    assert tasks[0].status == "queued"
    assert job.total_tasks == 1

@pytest.mark.asyncio
async def test_variant_expansion_cartesian(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(project_name="test", expansions=[
        VariantExpansion(
            plugin="example", task_type="generate_image",
            param_template={"prompt": "A {character} in {style}"},
            expand_over={"character": ["bull", "bear"], "style": ["anime", "realistic"]},
            variants=2,
        )
    ])
    job = await scheduler.schedule_job(spec)
    tasks = await db.get_tasks(job_id=job.id)
    # 2 characters * 2 styles * 2 variants = 8
    assert len(tasks) == 8
    assert job.total_tasks == 8
    # Verify placeholders resolved
    payloads = [json.loads(t.payload_json) for t in tasks]
    prompts = {p["prompt"] for p in payloads}
    assert "A bull in anime" in prompts
    assert "A bear in realistic" in prompts

@pytest.mark.asyncio
async def test_global_params_merged(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(
        project_name="test",
        global_params={"aspect_ratio": "16:9"},
        tasks=[TaskSpec(plugin="example", task_type="generate_image", params={"prompt": "hi"})],
    )
    job = await scheduler.schedule_job(spec)
    tasks = await db.get_tasks(job_id=job.id)
    payload = json.loads(tasks[0].payload_json)
    assert payload["aspect_ratio"] == "16:9"

@pytest.mark.asyncio
async def test_rejects_unknown_plugin(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(project_name="test", tasks=[
        TaskSpec(plugin="nonexistent", task_type="gen", params={})
    ])
    with pytest.raises(ValueError, match="Unknown plugin"):
        await scheduler.schedule_job(spec)

@pytest.mark.asyncio
async def test_rejects_unknown_task_type(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(project_name="test", tasks=[
        TaskSpec(plugin="example", task_type="nonexistent", params={})
    ])
    with pytest.raises(ValueError, match="Unknown task type"):
        await scheduler.schedule_job(spec)

@pytest.mark.asyncio
async def test_dependencies(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(project_name="test", tasks=[
        TaskSpec(plugin="example", task_type="generate_image", params={"prompt": "hi"}, ref_id="step1"),
        TaskSpec(plugin="example", task_type="upscale_image", params={"input_image": "x"}, depends_on="step1"),
    ])
    job = await scheduler.schedule_job(spec)
    tasks = await db.get_tasks(job_id=job.id)
    queued = [t for t in tasks if t.status == "queued"]
    blocked = [t for t in tasks if t.status == "blocked"]
    assert len(queued) == 1
    assert len(blocked) == 1
    assert blocked[0].depends_on_task_id == queued[0].id

@pytest.mark.asyncio
async def test_pipelines_not_created_at_submission(db, registry):
    scheduler = Scheduler(db, registry)
    spec = JobSpec(
        project_name="test",
        tasks=[TaskSpec(plugin="example", task_type="generate_image", params={"prompt": "hi"}, ref_id="imgs")],
        pipelines=[PipelineStep(source_ref="imgs", plugin="example", task_type="upscale_image",
                                param_template={"input_image": "{artifact_path}"})],
    )
    job = await scheduler.schedule_job(spec)
    tasks = await db.get_tasks(job_id=job.id)
    # Only the explicit task, no pipeline tasks yet
    assert len(tasks) == 1

def test_expand_variants_simple():
    from app.schemas import VariantExpansion
    exp = VariantExpansion(
        plugin="x", task_type="y",
        param_template={"prompt": "{a} and {b}"},
        expand_over={"a": ["X", "Y"], "b": ["1", "2"]},
        variants=1,
    )
    result = expand_variants(exp, {})
    assert len(result) == 4
    prompts = {r["prompt"] for r in result}
    assert prompts == {"X and 1", "X and 2", "Y and 1", "Y and 2"}
