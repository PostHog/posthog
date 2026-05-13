"""
Convert a SyntheticTest step list into an executable Playwright (Python) script.

The step list is the source of truth — the Playwright script is regenerated
deterministically on every run. There is no LLM at execution time.
"""

import json
from collections.abc import Callable
from typing import Any

INDENT = "            "  # 12 spaces: inside `def run(): with ...: try:`


def _quote(value: Any) -> str:
    """Safely embed a Python value as a string literal in the generated script."""
    return json.dumps(value)


_STEP_TEMPLATES: dict[str, Callable[[dict], str]] = {
    "navigate": lambda s: f"{INDENT}page.goto({_quote(s['url'])})",
    "click": lambda s: f"{INDENT}page.click({_quote(s['selector'])})",
    "type": lambda s: f"{INDENT}page.fill({_quote(s['selector'])}, {_quote(s.get('value', ''))})",
    "wait": lambda s: f"{INDENT}page.wait_for_timeout({int(s.get('duration_ms', 1000))})",
    "wait_for_selector": lambda s: f"{INDENT}page.wait_for_selector({_quote(s['selector'])})",
    "assert_element_exists": lambda s: (
        f"{INDENT}assert page.locator({_quote(s['selector'])}).count() > 0, "
        f"{_quote('Expected selector to exist: ' + s['selector'])}"
    ),
    "assert_url_contains": lambda s: (
        f"{INDENT}assert {_quote(s['value'])} in page.url, {_quote('Expected URL to contain: ' + s['value'])}"
    ),
    "assert_text_visible": lambda s: (
        f"{INDENT}assert page.get_by_text({_quote(s['value'])}).first.is_visible(), "
        f"{_quote('Expected text to be visible: ' + s['value'])}"
    ),
}


def steps_to_playwright(steps: list[dict], target_url: str | None = None) -> str:
    """
    Render a list of step dicts as a self-contained Playwright Python script.

    Each line corresponds to one step. Failures surface as either an assertion
    error (for assert_* steps) or a Playwright timeout/exception (for action
    steps). The runner records which step index raised so failures are pinpointed.
    """
    body_lines: list[str] = []
    if target_url and (not steps or steps[0].get("type") != "navigate"):
        body_lines.append(_STEP_TEMPLATES["navigate"]({"url": target_url}))

    for idx, step in enumerate(steps):
        step_type = step.get("type")
        if step_type not in _STEP_TEMPLATES:
            body_lines.append(
                f"{INDENT}raise ValueError('Unsupported step type at index {idx}: ' + {_quote(str(step_type))})"
            )
            continue
        body_lines.append(f"{INDENT}# step {idx}: {step_type}")
        body_lines.append(_STEP_TEMPLATES[step_type](step))

    body = "\n".join(body_lines) if body_lines else f"{INDENT}pass"
    return f"""from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
{body}
        finally:
            browser.close()


if __name__ == "__main__":
    run()
"""
