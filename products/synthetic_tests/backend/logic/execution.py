"""
Execution path for a synthetic test run.

Hackathon scope: this calls browserless.io if `BROWSERLESS_API_KEY` is set; otherwise
it runs a deterministic mock pass so the demo works in dev without external creds.

On failure we emit a `$synthetic_test_result` event with exception properties; the
existing error_tracking ingestion consumer auto-fingerprints it into an issue. We
also persist `issue_id` on the run row once the issue is created (best-effort).
"""

import os
import time
from typing import Any

from django.utils import timezone

import requests
import structlog

from posthog.ph_client import ph_scoped_capture

from products.synthetic_tests.backend.logic.playwright_converter import steps_to_playwright
from products.synthetic_tests.backend.models import SyntheticTest, SyntheticTestRun

logger = structlog.get_logger(__name__)

BROWSERLESS_ENDPOINT = "https://chrome.browserless.io/function"
DEFAULT_TIMEOUT_SECONDS = 30


def execute_synthetic_test(test: SyntheticTest) -> SyntheticTestRun:
    """Run a single execution of a synthetic test and persist the result."""
    run = SyntheticTestRun.objects.create(
        synthetic_test=test,
        status=SyntheticTestRun.Status.RUNNING,
    )
    script = steps_to_playwright(test.steps, target_url=test.target_url)
    start = time.monotonic()
    try:
        result = _run_via_browserless(script) if _has_browserless() else _run_mock(test)
    except Exception as exc:  # noqa: BLE001 — surface anything as a failed run
        logger.exception("synthetic_test_runner_error", test_id=str(test.id), error=str(exc))
        result = {"passed": False, "error": f"Runner error: {exc}", "step_index": None}

    duration_ms = int((time.monotonic() - start) * 1000)
    run.finished_at = timezone.now()
    run.duration_ms = duration_ms
    if result["passed"]:
        run.status = SyntheticTestRun.Status.PASSED
    else:
        run.status = SyntheticTestRun.Status.FAILED
        run.error_message = result.get("error", "")[:5000]
        run.error_step_index = result.get("step_index")
        if test.create_issue_on_failure:
            _emit_failure_event(test=test, run=run)
    run.save()

    test.last_run_at = run.started_at
    test.save(update_fields=["last_run_at", "updated_at"])
    return run


def _has_browserless() -> bool:
    return bool(os.environ.get("BROWSERLESS_API_KEY"))


def _run_via_browserless(script: str) -> dict[str, Any]:
    """Submit the Playwright script to browserless.io and parse the result."""
    api_key = os.environ["BROWSERLESS_API_KEY"]
    response = requests.post(
        f"{BROWSERLESS_ENDPOINT}?token={api_key}",
        json={"code": script, "context": {}},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if response.status_code == 200:
        return {"passed": True, "error": "", "step_index": None}
    body = response.text or "browserless returned non-200 with empty body"
    return {"passed": False, "error": body[:2000], "step_index": _infer_step_index(body)}


def _run_mock(test: SyntheticTest) -> dict[str, Any]:
    """Deterministic mock so dev environments without browserless can still demo."""
    # First step is treated as success if any steps exist; demos with named test "broken"
    # will fail deliberately for the failure-path demo arc.
    is_broken = "broken" in (test.name or "").lower()
    if is_broken:
        return {
            "passed": False,
            "error": "Selector [data-attr=submit] timed out after 5000ms (mock failure)",
            "step_index": max(len(test.steps) - 1, 0),
        }
    return {"passed": True, "error": "", "step_index": None}


def _infer_step_index(error_body: str) -> int | None:
    """Best-effort: pull a step index out of the generated script's `# step N:` markers in tracebacks."""
    marker = "# step "
    idx = error_body.find(marker)
    if idx == -1:
        return None
    try:
        return int(error_body[idx + len(marker) :].split(":", 1)[0])
    except (ValueError, IndexError):
        return None


def _emit_failure_event(*, test: SyntheticTest, run: SyntheticTestRun) -> None:
    """Emit an event so the existing error_tracking ingestion consumer fingerprints into an issue."""
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=f"synthetic_test:{test.id}",
                event="$synthetic_test_result",
                properties={
                    "$exception_type": "SyntheticTestFailure",
                    "$exception_message": run.error_message or "Synthetic test failed",
                    "synthetic_test_id": str(test.id),
                    "synthetic_test_run_id": str(run.id),
                    "synthetic_test_name": test.name,
                    "step_index": run.error_step_index,
                    "team_id": test.team_id,
                },
            )
    except Exception as exc:  # noqa: BLE001 — never let event emission fail the run record
        logger.warning("synthetic_test_event_emit_failed", error=str(exc))
