"""
CSS selectors for the example service.

Organize selectors by flow step. When building a real plugin, map these
to actual DOM elements on the target site. Use browser DevTools to find
the correct selectors.

Naming convention:
  - ALL_CAPS for constants
  - Group by flow (auth, generation, upscale, common)
  - Add comments explaining what each selector targets
"""

# --- Auth / Login Detection ---
# Used by detect_auth_required() to check if user needs to log in
LOGIN_FORM = "form#login"
LOGIN_USERNAME = "input[name='username']"
LOGIN_PASSWORD = "input[name='password']"
LOGIN_BUTTON = "button[type='submit']"

# Selector that indicates the user IS logged in (e.g., avatar, dashboard element)
LOGGED_IN_INDICATOR = ".user-avatar, .dashboard-nav"

# --- Common ---
# Error messages that may appear on any page
ERROR_BANNER = ".error-banner, .alert-error"
RATE_LIMIT_MESSAGE = ".rate-limit-warning"

# --- Image Generation Flow ---
# Step 1: Navigate and enter prompt
PROMPT_INPUT = "textarea#prompt"
PROMPT_CHAR_COUNT = ".char-count"

# Step 2: Configure settings
ASPECT_RATIO_SELECT = "select#aspect-ratio"
STYLE_REF_INPUT = "input#style-reference"
QUALITY_SLIDER = "input[type='range']#quality"

# Step 3: Submit and wait
GENERATE_BUTTON = "button#generate"
PROGRESS_BAR = ".progress-bar"
PROGRESS_PERCENT = ".progress-percent"
GENERATING_SPINNER = ".generating-spinner"

# Step 4: Download result
RESULT_IMAGE = "img.result-image"
RESULT_CONTAINER = ".result-container"
DOWNLOAD_BUTTON = "a.download-btn, button.download-btn"

# --- Upscale Flow ---
UPSCALE_INPUT = "input[type='file']#upscale-input"
UPSCALE_FACTOR_SELECT = "select#scale-factor"
UPSCALE_BUTTON = "button#upscale"
UPSCALE_PROGRESS = ".upscale-progress"
UPSCALE_RESULT = "img.upscale-result"
UPSCALE_DOWNLOAD = "a.upscale-download"
