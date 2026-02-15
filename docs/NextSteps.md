1) Plugin Builder workflow

A wizard in the dashboard:
	•	register plugin manifest
	•	upload a “selectors map” JSON
	•	test steps (health check, login check, minimal flow)

Even if it’s basic, it turns “write Python” into “configure and validate”.

2) Job templates, not raw JSON

Provide:
	•	“Generate images” template
	•	“Upload → render video” template
	•	“Batch with variants” template

And a UI form that fills the JSON for them.

JSON stays as the underlying spec, but most users never touch it.

3) Strong error messages + self-diagnosis

When something breaks, users need:
	•	“Selector missing: #submitButton”
	•	screenshot
	•	link to plugin docs step
	•	one-click “run health check”

This cuts support load massively.

4) A first-class “needs human” loop

You already have this, but make it feel polished:
	•	clear instructions (“Open worker headed and log in, then click Retry”)
	•	show last successful step
	•	show the exact URL where it got stuck

5) Versioning + compatibility checks

Plugins will drift as websites change.
Add:
	•	plugin version stored on server
	•	worker sends plugin version on register
	•	server warns if worker plugin != registered manifest version
	•	“last documented at” from manifest shown in UI

6) Packaging

For “others”, the install story is everything.

The friendliest path:
	•	Docker Compose for server
	•	“Worker package” as a one-liner install + run
	•	sensible defaults

If you can make “install worker” a single command, adoption jumps.







⸻

noapi — Usability Enhancements for Semi-Technical Teams (v1.5 Product Layer)

Objective

Transform noapi from a powerful internal automation framework into a usable product for semi-technical teams (agencies, technical creators, internal ops teams).

Target user:
	•	Comfortable with Docker and CLI
	•	Can edit JSON/YAML
	•	Can adjust CSS selectors if needed
	•	Does not want to modify core Python
	•	Does not want to debug system internals

The core architecture (plugins, queue, workers, artifacts, pipelines) remains unchanged.
This document defines usability enhancements layered on top.

⸻

1. Config-Driven Plugin Builder (Low-Code Plugin Mode)

Problem

Currently, creating a plugin requires writing Python flows. This limits adoption.

Enhancement

Introduce Level 1 Config Plugins: YAML-defined automation flows interpreted by the core engine.

Structure

plugins/{plugin_name}/
  manifest.json
  flow.yaml
  selectors.yaml
  README.md

flow.yaml Example

task_types:
  - name: generate_image
    steps:
      - action: goto
        url: "{base_url}"
      - action: type
        selector: "textarea.prompt"
        value: "{prompt}"
      - action: click
        selector: "button.submit"
      - action: wait_for
        selector: ".result-ready"
      - action: download
        selector: ".download-button"
        kind: "image"

Supported Step Types (v1)
	•	goto
	•	click
	•	type
	•	wait_for
	•	wait_for_timeout
	•	download
	•	screenshot
	•	extract_text

Behavior
	•	Core interprets YAML into Playwright actions.
	•	Python plugin mode still exists for advanced flows.
	•	Dashboard shows whether plugin is “config” or “python”.

Result

80% of common site automations become configuration-only.

⸻

2. Job Builder Wizard (Replace Raw JSON UX)

Problem

Uploading raw JobSpec JSON is intimidating.

Enhancement

Add a multi-step job creation wizard in the dashboard.

Wizard Flow
	1.	Select Plugin
	2.	Select Task Type (auto-generated from manifest)
	3.	Fill Parameter Form (schema-driven)
	4.	Add Variant Expansion (GUI cartesian builder)
	5.	Optional Pipeline Step
	6.	Review & Submit

Implementation
	•	Form fields auto-generated from manifest params_schema
	•	Expansion builder lets user add:
	•	Variable name
	•	List of values
	•	Variant count

JSON remains underlying format but hidden by default.

Result

Users never need to manually write job specs.

⸻

3. Guided Error Recovery & Selector Diagnostics

Problem

When selectors break, users don’t know what failed.

Enhancement

Add a structured failure panel per task.

On Failure Display:
	•	Step name
	•	Selector used
	•	URL at time of failure
	•	Screenshot
	•	Error classification

Add:

“Run Selector Test” button

This triggers plugin.health_check() and returns:
	•	Which selectors found
	•	Which missing
	•	Response time

Optional:

Highlight failing selector in dashboard UI.

Result

Debugging becomes mechanical, not guesswork.

⸻

4. Visible Session Management UX

Problem

Browser session state is invisible and confusing.

Enhancement

Add Worker Session Panel.

Display:
	•	Worker ID
	•	Plugin
	•	Headed / Headless
	•	Last login time
	•	Last activity time
	•	Session status: Valid / Expired / Unknown

Add:
	•	“Login Required” indicator
	•	Clear instructions panel:
	1.	Start worker in headed mode
	2.	Log in manually
	3.	Click Retry

Result

Human intervention becomes guided and predictable.

⸻

5. Plugin Versioning & Drift Management

Problem

Sites change. Plugins drift. Teams need clarity.

Enhancement

When worker registers:
	•	Store plugin version
	•	Store documented_at
	•	Store hash of manifest

Dashboard shows:
	•	Registered version
	•	Worker version
	•	Version mismatch warnings
	•	“Plugin outdated” flag

Optional:
Add “Last successful task” timestamp per plugin.

Result

Teams can manage plugin maintenance intentionally.

⸻

6. One-Command Deploy & Worker Packaging

Problem

Installation friction kills adoption.

Enhancement

Provide:
	•	docker-compose.yml
	•	Caddyfile.example
	•	.env template
	•	Volume-mounted data directory

Server Startup:

docker compose up -d

Worker Install:

pip install noapi-worker
noapi-worker --server https://example.com --plugin foo

Include:
	•	Automatic Playwright browser install check
	•	Clear startup validation logs

Result

Installation takes under 5 minutes.

⸻

7. Opinionated Defaults (Reduce Cognitive Load)

Problem

Too many tunables overwhelm semi-technical users.

Enhancement

Hard defaults:
	•	max_attempts: 3
	•	heartbeat_interval: 30s
	•	stale_timeout: 120s
	•	pipeline pick mode default: first
	•	artifact retention: indefinite
	•	naming_prefix: job_id if not provided

Advanced configuration exposed only in:
	•	Environment variables
	•	“Advanced Settings” collapsible UI panel

Result

System feels predictable and safe out of the box.

⸻

Additional UX Improvements (Optional but High Value)

Worker Health View
	•	Show running tasks
	•	Show average task duration
	•	Show failure rate

Artifact Explorer Enhancements
	•	Filter by plugin
	•	Filter by task type
	•	Filter by duplicate
	•	Preview inline

Audit Log
	•	Job submitted
	•	Worker registered
	•	Task retried
	•	Plugin updated

⸻

Final Product Positioning After Enhancements

With these 7 improvements, noapi becomes:
	•	A low-code browser automation engine
	•	A site-to-skill adapter platform
	•	A batch automation control plane
	•	Usable by agencies and internal teams
	•	Maintainable without modifying core code

It transitions from:
“Automation framework”

To:
“Programmable UI API layer with a dashboard.”

⸻