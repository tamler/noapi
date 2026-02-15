# Creating a noapi Plugin

## Quick Start

1. Copy this `_example` directory to `plugins/your_plugin_name/`
2. Edit `manifest.json` with your site's task types and parameters
3. Map real CSS selectors in `selectors.py` using browser DevTools
4. Implement actual browser flows in `flows.py`
5. Add error detection patterns in `errors.py`

## Directory Structure

```
plugins/your_plugin/
  __init__.py          # Empty (required for Python package)
  manifest.json        # Plugin metadata, task types, param schemas
  selectors.py         # All CSS selectors organized by flow
  flows.py             # SiteFlowBase subclass with browser automation
  errors.py            # Error detection utilities
  README.md            # Plugin-specific documentation
```

## manifest.json

Defines what your plugin can do:
- `name`: Machine-readable identifier (must match directory name)
- `auth_url`: Where the login page is (for the auth helper)
- `base_url`: Main application URL
- `capabilities.task_types`: What tasks this plugin handles

Each task type specifies:
- `params_schema`: Parameters with types, required flags, defaults, enums
- `artifact_kind`: What type of artifact this produces (image, video, other)
- `typical_duration_s` / `max_timeout_s`: Timing hints

## flows.py

Your flow class must inherit from `SiteFlowBase` and implement:

- `execute(page, task_payload, download_dir)` -> `FlowResult`
- `detect_auth_required(page)` -> `bool`
- `health_check(page)` -> `HealthCheckResult`

Import base classes from the core:
```python
from app.schemas import SiteFlowBase, FlowResult, NeedsHumanError, FlowError, HealthCheckResult
```

When login/captcha/verification is detected, raise `NeedsHumanError`.
When a retryable error occurs, raise `FlowError`.

## selectors.py

Keep all CSS selectors in one file:
- Use ALL_CAPS constants
- Group by flow step
- Add comments explaining what each selector targets
- Use browser DevTools to find correct selectors

## Testing Your Plugin

```bash
# 1. Save your browser session (manual login)
python -m app.cli.auth --plugin your_plugin --headed

# 2. Start a worker
python -m app.cli.worker --server http://localhost:8000 --plugin your_plugin --worker-id test1 --headed
```

## Tips

- Use `page.wait_for_selector()` with reasonable timeouts
- Always check for auth before executing flows
- Take screenshots on errors for debugging
- Use the `download_artifact()` helper from `app.workers.browser` for file downloads
- Check for site-specific errors after each major action
