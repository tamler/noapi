# noapi — Prompt 2: Site Onboarding Kit

You are an expert automation engineer. You have an existing codebase called **noapi** — a generic browser automation service with a plugin interface. You need to build the tooling that makes it easy to onboard a new website as a plugin.

## Context

The noapi core service is already built (see codebase). It has:
- A FastAPI server with job queue, worker protocol, and artifact storage.
- A plugin interface: each site plugin has a `manifest.json`, `selectors.py`, `flows.py`, `errors.py`.
- Workers that load a plugin and execute browser automation flows.

This prompt builds the **onboarding toolkit** — the tools and templates that take raw browser flow documentation (produced by a human or browser agent inspecting a website) and turn it into a working noapi plugin.

## Deliverables

### 1. Browser Flow Documentation Template

Create `tools/flow_doc_template.md` — the structured format that a browser agent (or human) fills out when documenting a website's UI flows. This template must capture everything needed to build a plugin.

```markdown
# Site Flow Documentation: {Service Name}

## Plugin Info
- **Plugin Name**: {machine-friendly name used as the plugin directory name, e.g., "midjourney"}
- **Display Name**: {human-friendly, e.g., "Midjourney"}
- **Base URL**: {the main app URL after login}
- **Auth URL**: {login page URL}
- **Auth Method**: browser_session
- **Date Documented**: {YYYY-MM-DD}

## Authentication
- **Login detection**: {how to know user is logged in — selector, URL pattern, etc.}
- **Logout/expired detection**: {what happens when session expires — redirect URL, modal selector, error text}
- **Session storage**: {cookie-based, localStorage token, etc.}
- **Typical session duration**: {hours/days before re-auth needed}

## Task Type: {task_type_name}

### Description
{What this task does, e.g., "Generate an image from a text prompt"}

### Parameters
| Parameter | Type | Required | Default | Enum Values | Description |
|-----------|------|----------|---------|-------------|-------------|
| prompt | string | yes | — | — | The text prompt for generation |
| aspect_ratio | string | no | "1:1" | "1:1","16:9","9:16" | Output aspect ratio |

### Artifact Output
- **Kind**: {image | video | other}
- **Format**: {png, jpg, mp4, webm, etc.}
- **Typical size range**: {e.g., "2-8 MB"}
- **Typical generation time**: {e.g., "30-90 seconds"}

### Browser Flow Steps

#### Step 1: {Action Name}
- **Action**: {navigate | click | type | upload_file | select_dropdown | wait | scroll}
- **Target**:
  - Primary selector: `{CSS selector}`
  - Fallback selector: `{alternative CSS selector or XPath}`
  - Aria/data attribute: `{data-testid, aria-label, etc. — more stable}`
  - Human description: "{e.g., the prompt input textarea at the bottom of the page}"
- **Input**: {what to type/upload/select — map to parameter name, e.g., "{prompt}"}
- **Pre-condition**: {what must be true before this step, e.g., "page fully loaded, no modals"}
- **Expected result**: {what changes after this step}
- **Wait after**: {selector to wait for, or fixed delay, before next step}
  - Selector: `{element that appears/changes}`
  - Timeout: {seconds}

#### Step 2: ...
(repeat for each step)

### Completion Detection
- **Method**: {selector_appears | network_idle | polling | mutation_observer}
- **Success indicator**: `{selector or condition}`
- **Polling interval**: {seconds, if applicable}
- **Typical wait**: {range, e.g., "30-120 seconds"}
- **Max timeout**: {seconds before giving up}

### Artifact Download
- **Method**: {click_download_button | extract_src_url | right_click_save | intercept_network}
- **Download trigger**: `{selector to click, or network URL pattern to intercept}`
- **URL extraction**: `{if src extraction: selector + attribute, e.g., img.result[src]}`
- **File lands in**: {browser download dir | blob URL | direct URL}
- **Filename pattern**: {how the service names files, if known}
- **Direct CDN URL pattern**: `{regex or glob, e.g., "*.cdn.example.com/outputs/*"}`

### Error States

#### Rate Limited
- **Detection**: `{selector or text content}`
- **Recommended action**: backoff {duration}

#### Generation Failed
- **Detection**: `{selector or text}`
- **Recommended action**: retry | fail

#### Content Filtered / Rejected
- **Detection**: `{selector or text}`
- **Recommended action**: fail (do not retry)

#### Session Expired
- **Detection**: `{URL redirect pattern or selector}`
- **Recommended action**: needs_human "Re-authentication required"

#### Unknown Error
- **Detection**: catch-all after timeout
- **Recommended action**: screenshot + needs_human

### Network Observations
Document significant API calls the UI makes (visible in browser Network tab). These may allow shortcuts.

| Endpoint | Method | Request Key Fields | Response Key Fields | Auth | Notes |
|----------|--------|-------------------|---------------------|------|-------|
| /api/generate | POST | { prompt, params } | { job_id, status } | Cookie | Could potentially call directly |
| /api/status/{id} | GET | — | { status, output_url } | Cookie | Polling endpoint |

### UI Fragility Notes
- **Stable anchors**: {data-testid attributes, aria labels, structural selectors that are unlikely to change}
- **Fragile elements**: {dynamically generated class names, minified classes, etc.}
- **Known gotchas**: {e.g., "The app uses shadow DOM for the prompt area", "Results load in an iframe"}
- **Last verified**: {date}

---
(Repeat "## Task Type" section for each task type the service supports)
```

### 2. Plugin Generator Script

Create `tools/generate_plugin.py` — a CLI tool that reads a completed flow documentation file and scaffolds a plugin.

```bash
python tools/generate_plugin.py \
  --doc tools/flows/midjourney_flows.md \
  --output plugins/midjourney/
```

The generator should:

1. **Parse the flow doc** (use a simple markdown parser or regex — the template is structured enough):
   - Extract service info -> `manifest.json`
   - Extract parameters per task type -> manifest `params_schema`
   - Extract selectors -> `selectors.py` (organized as a Python class with constants)
   - Extract flow steps -> `flows.py` (skeleton with TODO comments for each step)
   - Extract error states -> `errors.py` (detection functions)

2. **Generate `manifest.json`**:
   - Populated with all extracted metadata
   - `documented_at` set from the flow doc date
   - `capabilities.task_types` populated from each documented task type
   - Convert the Parameters table (markdown) to the manifest's `params_schema` JSON format:
     - Table column "Type" -> `"type"` field
     - Table column "Required" (yes/no) -> `"required"` (true/false)
     - Table column "Default" -> `"default"` field (omit if "—")
     - Table column "Enum Values" -> `"enum"` array (omit if "—")
     - Table column "Description" -> `"description"` field
   - Plugin `"name"` field must match the directory name and is what gets used as the `"plugin"` value in job specs

3. **Generate `selectors.py`**:
   ```python
   """
   Selectors for {display_name}.
   Auto-generated from flow documentation dated {date}.

   IMPORTANT: UI selectors change frequently. If automation fails,
   re-document the site and regenerate, or update selectors manually.
   """

   class {Name}Selectors:
       # Auth detection
       LOGGED_IN_INDICATOR = "{selector}"
       LOGIN_REDIRECT_URL = "{url_pattern}"

       # Task: generate_image
       class GenerateImage:
           PROMPT_INPUT = "{selector}"
           PROMPT_INPUT_FALLBACK = "{fallback}"
           SUBMIT_BUTTON = "{selector}"
           # ... etc

           # Completion
           RESULT_READY = "{selector}"

           # Download
           DOWNLOAD_BUTTON = "{selector}"
           RESULT_IMAGE_SRC = "{selector}"

           # Errors
           RATE_LIMIT_INDICATOR = "{selector}"
           GENERATION_FAILED = "{selector}"
           CONTENT_FILTERED = "{selector}"
   ```

4. **Generate `flows.py`**:
   - Import the base class from noapi core
   - Create a flow class per task type
   - Each step from the flow doc becomes a method call with the selector and a TODO comment
   - Include auth detection from the documented selectors
   - Include screenshot-on-error wrapping
   - The generated code should be **runnable as-is** for the happy path if selectors are correct

5. **Generate `errors.py`**:
   - Error detection functions for each documented error state
   - Map to the appropriate action (retry, needs_human, fail)

6. **Generate `README.md`**:
   - Service description
   - Setup instructions (auth helper)
   - List of supported task types and parameters
   - Staleness warning with documented date

### 3. Plugin Validator

Create `tools/validate_plugin.py` — validates a plugin directory is complete and correct.

```bash
python tools/validate_plugin.py plugins/midjourney/
```

Checks:
- `manifest.json` exists and validates against the manifest schema
- All declared task types have corresponding flow classes in `flows.py`
- All flow classes inherit from `SiteFlowBase`
- `selectors.py` exists and has no empty string selectors (warn, don't error)
- `errors.py` exists
- `README.md` exists
- `documented_at` is present and warns if older than 30 days

### 4. Flow Doc Diff Tool

Create `tools/diff_flows.py` — compares two versions of a flow doc to highlight what changed.

```bash
python tools/diff_flows.py \
  tools/flows/midjourney_flows_v1.md \
  tools/flows/midjourney_flows_v2.md
```

This is useful when re-documenting a site after UI changes. It shows:
- New/removed task types
- Changed selectors (highlight which ones)
- Changed flow steps
- Changed error detection

Output as a readable diff summary, not a raw text diff.

### 5. Community Contribution Template

Create `CONTRIBUTING.md` at the repo root with:
- How to document a new site (use the flow doc template)
- How to generate a plugin from documentation
- How to validate before submitting a PR
- Plugin quality guidelines:
  - Must include documented_at date
  - Must not include credentials or session data
  - Must not bypass auth, captchas, or ToS protections
  - Must include clear README with what the plugin automates
  - Selectors should prefer stable anchors (data attributes, aria labels) over class names
- Acceptable use policy: plugins are for sites you have legitimate access to

### Folder Structure Addition

```
noapi/
  tools/
    flow_doc_template.md              # The blank template
    generate_plugin.py                # Plugin scaffolder
    validate_plugin.py                # Plugin validator
    diff_flows.py                     # Flow doc differ
    flows/                            # Where documented flows live (gitignored except examples)
      _example_flows.md               # Example filled-out flow doc for reference
  CONTRIBUTING.md
```

## Implementation Notes

- The generator doesn't need to be perfect — it scaffolds 80% and the developer refines. Comments and TODOs should guide the refinement.
- Parse the flow doc template with regex or a simple state machine. Don't over-engineer with a full markdown AST parser.
- The generated `flows.py` should use the Playwright helpers from `app/workers/browser.py` in the core (wait_with_timeout, screenshot_on_error, download_artifact).
- All tools should work standalone with no server running — they're development-time utilities.
