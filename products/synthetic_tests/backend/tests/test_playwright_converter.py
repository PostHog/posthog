"""Tests for the step list → Playwright Python converter."""

from parameterized import parameterized

from products.synthetic_tests.backend.logic.playwright_converter import steps_to_playwright


def _compile(script: str) -> None:
    compile(script, "<synthetic-test>", "exec")


def test_empty_steps_compiles() -> None:
    script = steps_to_playwright([])
    _compile(script)
    assert "pass" in script


def test_target_url_prepends_navigate_when_steps_dont_start_with_one() -> None:
    script = steps_to_playwright([{"type": "click", "selector": "[data-attr=btn]"}], target_url="https://example.com")
    _compile(script)
    assert 'page.goto("https://example.com")' in script
    assert 'page.click("[data-attr=btn]")' in script


def test_target_url_not_prepended_when_first_step_is_navigate() -> None:
    script = steps_to_playwright([{"type": "navigate", "url": "https://other.com"}], target_url="https://example.com")
    _compile(script)
    assert 'page.goto("https://other.com")' in script
    assert 'page.goto("https://example.com")' not in script


@parameterized.expand(
    [
        ("navigate", [{"type": "navigate", "url": "https://example.com"}], 'page.goto("https://example.com")'),
        ("click", [{"type": "click", "selector": "[data-attr=submit]"}], 'page.click("[data-attr=submit]")'),
        (
            "type",
            [{"type": "type", "selector": "#email", "value": "a@b.com"}],
            'page.fill("#email", "a@b.com")',
        ),
        ("wait", [{"type": "wait", "duration_ms": 1500}], "page.wait_for_timeout(1500)"),
        (
            "wait_for_selector",
            [{"type": "wait_for_selector", "selector": ".loaded"}],
            'page.wait_for_selector(".loaded")',
        ),
        (
            "assert_element_exists",
            [{"type": "assert_element_exists", "selector": ".done"}],
            'page.locator(".done").count() > 0',
        ),
        (
            "assert_url_contains",
            [{"type": "assert_url_contains", "value": "/onboarding"}],
            '"/onboarding" in page.url',
        ),
        (
            "assert_text_visible",
            [{"type": "assert_text_visible", "value": "Welcome"}],
            'page.get_by_text("Welcome").first.is_visible()',
        ),
    ]
)
def test_each_step_type_renders_expected_call(label: str, steps: list[dict], expected_fragment: str) -> None:
    script = steps_to_playwright(steps)
    _compile(script)
    assert expected_fragment in script, f"{label}: expected fragment not found"


def test_step_indices_appear_as_comments() -> None:
    script = steps_to_playwright(
        [
            {"type": "navigate", "url": "https://example.com"},
            {"type": "click", "selector": ".x"},
        ]
    )
    _compile(script)
    assert "# step 0: navigate" in script
    assert "# step 1: click" in script


def test_unsupported_step_raises_at_runtime_not_at_render_time() -> None:
    script = steps_to_playwright([{"type": "double_click", "selector": ".x"}])
    _compile(script)
    assert "Unsupported step type at index 0" in script


def test_special_characters_in_values_are_escaped() -> None:
    script = steps_to_playwright([{"type": "type", "selector": "#q", "value": 'Hello "world" \n line'}])
    _compile(script)


def test_realistic_signup_flow_compiles() -> None:
    script = steps_to_playwright(
        [
            {"type": "navigate", "url": "https://us.posthog.com/signup"},
            {"type": "wait_for_selector", "selector": "[data-attr=signup-email]"},
            {"type": "type", "selector": "[data-attr=signup-email]", "value": "test+synth@posthog.com"},
            {"type": "type", "selector": "[data-attr=signup-password]", "value": "Hackathon123!"},
            {"type": "click", "selector": "[data-attr=signup-submit]"},
            {"type": "wait_for_selector", "selector": "[data-attr=onboarding-step-platform]"},
            {"type": "assert_url_contains", "value": "/onboarding"},
        ]
    )
    _compile(script)
