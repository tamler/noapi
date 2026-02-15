# noapi — Prompt 3: Skill Generator

You are an expert automation engineer familiar with Claude Code skills. You have an existing codebase called **noapi** — a generic browser automation service with a plugin system. Plugins define how to automate specific websites. You need to build a tool that **generates a Claude skill from a noapi plugin**, giving users a natural language interface to that specific site's capabilities.

## Context

The noapi system has:
- A FastAPI server at a known URL (e.g., `https://klyption.com`) with job/task/artifact APIs.
- Site plugins with `manifest.json` declaring task types, parameters, and artifact kinds.
- Workers that execute browser automation and upload results.

A **generated skill** teaches Claude how to:
1. Understand what the site can do (from the manifest).
2. Translate natural language requests into structured job specs.
3. Submit jobs to the noapi API.
4. Poll for completion and present artifacts to the user.
5. Handle errors and needs_human situations conversationally.

## The Core Insight

Each site skill is **derived from** the plugin manifest. The manifest declares task types and their parameter schemas — this is everything Claude needs to construct valid job specs. The skill generator reads the manifest and produces a skill tailored to that site.

## Deliverables

### 1. Skill Generator Script

Create `tools/generate_skill.py`:

```bash
python tools/generate_skill.py \
  --plugin plugins/midjourney/ \
  --server-url https://klyption.com \
  --output skills/midjourney/
```

The generator reads `plugins/{name}/manifest.json` and `plugins/{name}/README.md`, then produces:

```
skills/{plugin_name}/
  SKILL.md                 # The skill prompt (what Claude reads)
  examples.md              # Example conversations showing usage
  api_reference.md         # Generated API reference for the skill to consult
```

### 2. SKILL.md Generation

The generated `SKILL.md` should contain:

```markdown
# {Display Name} Automation Skill

You have access to a browser automation service (noapi) that can control {Display Name}
on behalf of the user. The service runs at `{server_url}`.

## What You Can Do

{For each task_type in manifest:}
### {task_type.name}: {task_type.description}

Parameters:
{For each param in task_type.params_schema:}
- **{param_name}** ({param_type}{", required" if required}): {description}
  {if enum:} Options: {enum_values}
  {if default:} Default: {default}

Artifact output: {task_type.artifact_kind} file

---

## How to Use the noapi API

All requests require the header `X-Worker-Key: {api_key}` (the user must provide this
or it should be configured in your environment).

### Submit a Job

POST {server_url}/api/jobs

Body (JSON):
```json
{
  "project_name": "descriptive name",
  "tasks": [
    {
      "plugin": "{plugin_name}",
      "task_type": "{task_type}",
      "params": { ... },
      "ref_id": "optional-reference"
    }
  ],
  "expansions": [
    {
      "plugin": "{plugin_name}",
      "task_type": "{task_type}",
      "param_template": { ... with {placeholders} ... },
      "expand_over": { "variable": ["val1", "val2"] },
      "variants": 1,
      "ref_id": "optional-reference"
    }
  ],
  "pipelines": [
    {
      "source_ref": "ref-of-upstream-tasks",
      "plugin": "{other_or_same_plugin}",
      "task_type": "{task_type}",
      "param_template": { "input_image": "{artifact_path}" },
      "outputs_per_input": 1
    }
  ],
  "global_params": {},
  "naming_prefix": "project_name"
}
```

### Check Job Status

GET {server_url}/api/jobs/{job_id}

Returns task counts by status. Poll every 5-10 seconds.

### Get Artifacts

GET {server_url}/api/artifacts?job_id={job_id}

Returns list of completed artifacts with download URLs.

### Handle Needs Human

When you see tasks in `needs_human` status, tell the user:
- What went wrong (show the error message)
- That they need to intervene (usually re-authenticate on the worker machine)
- Once resolved, they should tell you and you'll retry:
  POST {server_url}/api/tasks/{task_id}/retry

## Behavior Guidelines

1. **Always confirm before submitting large jobs.** If the expansion would create more than
   10 tasks, tell the user the count and ask for confirmation.

2. **Translate natural language to parameters.** When the user says:
{For each task_type, generate natural language mapping examples:}
   - "{example natural request}" -> task_type: {type}, params: { ... }

3. **Poll and report.** After submitting, poll job status every 10 seconds.
   Give the user progress updates. When complete, present artifacts.

4. **Handle partial failures gracefully.** If some tasks fail, report which ones
   succeeded, show artifacts from successes, and ask about retrying failures.

5. **Remember context.** If the user iterates ("make it wider", "try a different style"),
   modify the previous params accordingly and submit a new job.

## Common Patterns

### Single Generation
User: "Generate a {thing}"
-> Submit job with one task.

### Batch with Variants
User: "Generate {thing} in multiple styles/sizes"
-> Submit job with VariantExpansion using expand_over for the varying dimension.

### Pipeline
User: "Generate images of {thing} then make videos from the best ones"
-> Submit job with expansion for images + pipeline step for videos.
-> Note: pipeline auto-triggers when upstream completes. Tell user you'll monitor.

### Iteration
User: "I like #3 but make it more {adjective}"
-> Use the params from artifact #3, modify as requested, submit new single task.
```

### 3. examples.md Generation

Generate 3-5 example conversations showing realistic usage patterns for this specific plugin. Use the manifest's task types and parameters to make the examples concrete.

### 4. api_reference.md Generation

A condensed reference showing every API endpoint the skill uses, with request/response shapes. Generated from the noapi core API spec + the plugin manifest.

### 5. Skill Customization Step

After generation, the skill should be reviewed and optionally enhanced by the user:

- Add **domain-specific vocabulary mappings** (e.g., "widescreen" -> aspect_ratio "16:9")
- Add **common prompt patterns** for the service (e.g., Midjourney-style prompts differ from Stable Diffusion)
- Add **preference defaults** (e.g., "always use --v 6.1 unless I say otherwise")

The generator should include a clearly marked `## CUSTOMIZE` section in SKILL.md where these additions go, with commented examples.

### 6. Skill Installer

Create `tools/install_skill.py`:

```bash
# Install skill to Claude Code skills directory
python tools/install_skill.py \
  --skill skills/midjourney/ \
  --claude-skills-dir ~/.claude/skills/
```

This copies the skill files to the appropriate location and provides instructions for activating it.

## Implementation Notes

- The generator is a templating exercise. Read the manifest, fill in the templates.
- Use Jinja2 or simple string formatting — keep it straightforward.
- The most important part is the natural language -> parameter mapping examples. Generate these from the param schema: for each parameter with enum values, show how natural language maps to each option. For free-text params, show example phrasings.
- The skill should work with both Claude Code and Cowork mode (Claude desktop). The API calls can be made via bash (curl) in Claude Code or via the WebFetch/Bash tools in Cowork.
- Include a note in the generated SKILL.md about needing the `NOAPI_SERVER_URL` and `NOAPI_WORKER_KEY` configured (environment variables or hardcoded during generation).

## Folder Structure Addition

```
noapi/
  tools/
    generate_skill.py          # Skill generator
    install_skill.py           # Skill installer
  skills/                      # Generated skills live here
    _example/                  # Example generated skill (from the example plugin)
      SKILL.md
      examples.md
      api_reference.md
```
