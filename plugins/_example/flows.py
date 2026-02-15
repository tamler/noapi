"""
Example plugin flow implementations.

This is a TEMPLATE showing the expected structure for plugin flows.
It is NOT functional -- replace selectors and logic with real site interactions.

Each plugin must have at least one class that inherits from SiteFlowBase.
The worker discovers this class automatically via introspection.
"""
from __future__ import annotations

from app.schemas import (
    ArtifactSpec,
    FlowError,
    FlowResult,
    HealthCheckResult,
    NeedsHumanError,
    SiteFlowBase,
)

from . import selectors
from .errors import detect_error


class ExampleServiceFlow(SiteFlowBase):
    """Flow implementation for the example service.

    Replace all selector references and page interactions with
    real automation for your target site.
    """

    async def detect_auth_required(self, page) -> bool:
        """Check if the current page requires authentication.

        Strategy: Look for the logged-in indicator. If it's missing
        and a login form is present, auth is needed.
        """
        try:
            logged_in = await page.query_selector(selectors.LOGGED_IN_INDICATOR)
            if logged_in:
                return False
            login_form = await page.query_selector(selectors.LOGIN_FORM)
            return login_form is not None
        except Exception:
            return True

    async def execute(self, page, task_payload: dict, download_dir: str) -> FlowResult:
        """Execute a task based on its type (determined from payload).

        The worker calls this with the task's payload dict.
        Route to the appropriate flow based on task content.
        """
        # Determine which flow to run based on payload keys
        if "prompt" in task_payload:
            return await self._generate_image(page, task_payload, download_dir)
        elif "input_image" in task_payload:
            return await self._upscale_image(page, task_payload, download_dir)
        else:
            raise FlowError("Unknown task payload -- no recognized keys")

    async def _generate_image(self, page, payload: dict, download_dir: str) -> FlowResult:
        """Generate an image from a text prompt.

        Flow steps:
        1. Navigate to generation page
        2. Enter prompt text
        3. Set aspect ratio and optional style reference
        4. Click generate and wait for completion
        5. Download the result
        """
        prompt = payload["prompt"]
        aspect_ratio = payload.get("aspect_ratio", "1:1")

        # Step 1: Navigate (adjust URL for real site)
        # await page.goto("https://example.com/app/generate")

        # Step 2: Enter prompt
        # await page.fill(selectors.PROMPT_INPUT, prompt)

        # Step 3: Set options
        # if aspect_ratio != "1:1":
        #     await page.select_option(selectors.ASPECT_RATIO_SELECT, aspect_ratio)

        # Step 4: Generate
        # await page.click(selectors.GENERATE_BUTTON)
        # await page.wait_for_selector(selectors.RESULT_IMAGE, timeout=300000)

        # Step 5: Check for errors
        # error = await detect_error(page)
        # if error:
        #     error_type, message = error
        #     if error_type == "rate_limit":
        #         raise FlowError(f"Rate limited: {message}")
        #     raise FlowError(message)

        # Step 6: Download
        # from app.workers.browser import download_artifact
        # path = await download_artifact(
        #     page, lambda: page.click(selectors.DOWNLOAD_BUTTON), download_dir
        # )

        # Template return -- replace with actual artifacts
        # In a real plugin, you'd return:
        # return FlowResult(
        #     success=True,
        #     artifacts=[
        #         ArtifactSpec(
        #             kind="image",
        #             local_path=path,
        #             filename_hint=f"gen_{aspect_ratio}.png",
        #             metadata={"prompt": prompt, "aspect_ratio": aspect_ratio},
        #         )
        #     ],
        #     metadata={"prompt": prompt, "aspect_ratio": aspect_ratio},
        # )

        return FlowResult(
            success=True,
            artifacts=[],
            metadata={"prompt": prompt, "aspect_ratio": aspect_ratio},
        )

    async def _upscale_image(self, page, payload: dict, download_dir: str) -> FlowResult:
        """Upscale an existing image.

        Flow steps:
        1. Navigate to upscale page
        2. Upload source image
        3. Select scale factor
        4. Submit and wait
        5. Download result
        """
        input_image = payload["input_image"]
        scale_factor = payload.get("scale_factor", "2x")

        # Similar pattern to generate -- navigate, interact, wait, download
        # In a real plugin:
        # return FlowResult(
        #     success=True,
        #     artifacts=[
        #         ArtifactSpec(
        #             kind="image",
        #             local_path=downloaded_path,
        #             filename_hint=f"upscale_{scale_factor}.png",
        #             metadata={"scale_factor": scale_factor},
        #         )
        #     ],
        #     metadata={"input_image": input_image, "scale_factor": scale_factor},
        # )

        return FlowResult(
            success=True,
            artifacts=[],
            metadata={"input_image": input_image, "scale_factor": scale_factor},
        )

    async def health_check(self, page) -> HealthCheckResult:
        """Best-effort check of which selectors are present on the site."""
        found = []
        missing = []

        key_selectors = {
            "login_form": selectors.LOGIN_FORM,
            "prompt_input": selectors.PROMPT_INPUT,
            "generate_button": selectors.GENERATE_BUTTON,
        }

        for name, sel in key_selectors.items():
            try:
                el = await page.query_selector(sel)
                if el:
                    found.append(name)
                else:
                    missing.append(name)
            except Exception:
                missing.append(name)

        return HealthCheckResult(
            healthy=len(missing) == 0,
            selectors_found=found,
            selectors_missing=missing,
            message=f"Found {len(found)}/{len(key_selectors)} key selectors",
        )
