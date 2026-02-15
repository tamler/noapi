"""
Error detection for the example service.

Check the page for known error states after actions. Each error type
maps to a CSS selector and a human-readable message extraction strategy.
"""
from __future__ import annotations

from . import selectors


# Map error types to their selectors
ERROR_SELECTORS = {
    "rate_limit": selectors.RATE_LIMIT_MESSAGE,
    "general_error": selectors.ERROR_BANNER,
}


async def detect_error(page) -> tuple[str, str] | None:
    """Check page for known error states.

    Returns:
        (error_type, message) if an error is detected, None otherwise.

    Usage in flows:
        error = await detect_error(page)
        if error:
            error_type, message = error
            if error_type == "rate_limit":
                raise FlowError(f"Rate limited: {message}")
            raise FlowError(message)
    """
    for error_type, selector in ERROR_SELECTORS.items():
        try:
            element = await page.query_selector(selector)
            if element:
                message = await element.inner_text()
                return (error_type, message.strip())
        except Exception:
            continue
    return None
