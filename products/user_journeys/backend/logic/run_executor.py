"""Walk a journey's steps in a browser and judge each one.

The executor takes a `BrowserPage` and a plan and returns one outcome per step. It reads no database
and stores nothing, so the same code runs against Browserless in production, a local Chromium in
tests, and a fake page in unit tests.

Finding the element a click step targets lives in `run_elements`.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import re2
import structlog

from posthog.dataclasses import frozen

from ..facade.contracts import ElementClickStep, JourneyStep, PageviewStep
from ..facade.enums import JourneyRunStepStatus, JourneyStepFailureReason, UrlMatching
from .run_browser import BrowserPage, NavigationError
from .run_elements import URL_PREVIEW_LENGTH, StepFailure, element_failure, find_clickable, preview
from .run_urls import origin_of, replace_origin, step_url_pattern

logger = structlog.get_logger(__name__)

RUN_TIME_BUDGET_SECONDS = 180
NAVIGATION_TIMEOUT_MS = 30_000
# Network idle is a hint that a page has rendered, not a requirement, so this wait is short.
SETTLE_TIMEOUT_MS = 3_000
# How long a step waits for its element to become clickable, or for the page URL to match.
STEP_WAIT_MS = 5_000
POLL_INTERVAL_MS = 250


@frozen
class RunPlan:
    steps: list[JourneyStep]
    start_url: str
    # The origin the journey was recorded on, and the one this run replaces it with, if any.
    recorded_origin: str
    base_origin: str | None


@frozen
class StepOutcome:
    index: int
    status: JourneyRunStepStatus
    failure_reason: JourneyStepFailureReason | None
    message: str
    screenshot: bytes | None
    duration_ms: int | None


@frozen
class _Attempt:
    """What one step did, before it is timed and turned into an outcome."""

    failure: StepFailure | None
    # Set when the step captured its own screenshot, before a click changed the page.
    screenshot: bytes | None = None
    note: str = ""


def url_matches(url: str, pattern: str, matching: UrlMatching) -> bool:
    """The funnel's URL comparison: whole-URL equality, case-insensitive substring, or a regex search."""
    if matching == UrlMatching.EXACT:
        return _normalize_bare_origin(url) == _normalize_bare_origin(pattern)
    if matching == UrlMatching.CONTAINS:
        return pattern.casefold() in url.casefold()
    try:
        return re2.search(pattern, url) is not None
    except re2.error:
        return False


def _normalize_bare_origin(url: str) -> str:
    # Browsers report "https://example.com" as "https://example.com/", and the recorded URL may lack the slash.
    if url.count("/") == 2:
        return url + "/"
    return url


class StepExecutor:
    def __init__(self, page: BrowserPage, plan: RunPlan, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._page = page
        self._plan = plan
        self._clock = clock
        self._deadline = clock() + RUN_TIME_BUDGET_SECONDS

    def run(self) -> list[StepOutcome]:
        outcomes: list[StepOutcome] = []
        start_failure = self._open_start_url()
        for index, step in enumerate(self._plan.steps):
            if outcomes and outcomes[-1].status != JourneyRunStepStatus.PASSED:
                outcomes.append(_skipped(index))
                continue
            outcomes.append(self._run_step(index, step, start_failure if index == 0 else None))
        return outcomes

    def _open_start_url(self) -> StepFailure | None:
        try:
            status = self._page.goto(self._plan.start_url, timeout_ms=NAVIGATION_TIMEOUT_MS)
        except NavigationError as e:
            blocked = self._blocked_navigation()
            if blocked is not None:
                return blocked
            reason = JourneyStepFailureReason.TIMEOUT if e.timed_out else JourneyStepFailureReason.NAVIGATION_FAILED
            return StepFailure(reason=reason, message=str(e))
        if status is not None and status >= 400:
            return StepFailure(
                reason=JourneyStepFailureReason.NAVIGATION_FAILED,
                message=f"The start page responded with HTTP status {status}.",
            )
        self._page.wait_for_settled(timeout_ms=SETTLE_TIMEOUT_MS)
        return None

    def _run_step(self, index: int, step: JourneyStep, start_failure: StepFailure | None) -> StepOutcome:
        started = self._clock()
        attempt = self._attempt(step, start_failure)
        screenshot = attempt.screenshot if attempt.screenshot is not None else self._safe_screenshot()
        failure = attempt.failure
        return StepOutcome(
            index=index,
            status=JourneyRunStepStatus.FAILED if failure is not None else JourneyRunStepStatus.PASSED,
            failure_reason=failure.reason if failure is not None else None,
            message=f"{failure.message if failure is not None else ''} {attempt.note}".strip(),
            screenshot=screenshot,
            duration_ms=round((self._clock() - started) * 1000),
        )

    def _attempt(self, step: JourneyStep, start_failure: StepFailure | None) -> _Attempt:
        if self._clock() >= self._deadline:
            return _Attempt(
                failure=StepFailure(
                    reason=JourneyStepFailureReason.TIMEOUT,
                    message=f"The run reached its time limit of {RUN_TIME_BUDGET_SECONDS} seconds before this step.",
                )
            )
        if start_failure is not None:
            return _Attempt(failure=start_failure)
        url_failure = self._wait_for_url(step) or self._blocked_navigation()
        if url_failure is not None or isinstance(step, PageviewStep):
            return _Attempt(failure=url_failure)
        return self._click(step)

    def _click(self, step: ElementClickStep) -> _Attempt:
        verdict = self._poll(lambda: find_clickable(self._page, step), done=lambda found: found.is_final)
        note = f"{verdict.matches} elements match. The run used the first visible one." if verdict.matches > 1 else ""
        failure = element_failure(step, verdict)
        if failure is not None or verdict.x is None or verdict.y is None:
            return _Attempt(failure=failure, note=note)
        # The screenshot shows the element as the click finds it, before the click changes the page.
        screenshot = self._safe_screenshot()
        self._page.click(verdict.x, verdict.y)
        self._page.wait_for_settled(timeout_ms=SETTLE_TIMEOUT_MS)
        return _Attempt(failure=self._blocked_navigation(), screenshot=screenshot, note=note)

    def _wait_for_url(self, step: JourneyStep) -> StepFailure | None:
        """Wait for the page URL to match the step's, since after a click the page may still be navigating."""
        pattern = step_url_pattern(step)
        if pattern is None:
            return None
        url, matching = pattern

        def check() -> StepFailure | None:
            current = self._comparable_url()
            if url_matches(current, url, matching):
                return None
            return self._blocked_navigation() or StepFailure(
                reason=JourneyStepFailureReason.NAVIGATION_MISMATCH,
                message=(
                    f'Expected a page URL that matches "{preview(url, URL_PREVIEW_LENGTH)}" ({matching.value}), '
                    f'but the browser is on "{preview(current, URL_PREVIEW_LENGTH)}".'
                ),
            )

        failure = self._poll(
            check, done=lambda found: found is None or found.reason == JourneyStepFailureReason.NAVIGATION_BLOCKED
        )
        if failure is None:
            self._page.wait_for_settled(timeout_ms=SETTLE_TIMEOUT_MS)
        return failure

    def _poll[T](self, check: Callable[[], T], *, done: Callable[[T], bool]) -> T:
        """Repeat `check` until `done` accepts its answer or the step's wait runs out, and return the last answer."""
        wait_ms = max(0, min(STEP_WAIT_MS, round((self._deadline - self._clock()) * 1000)))
        waited_ms = 0
        while True:
            answer = check()
            if done(answer) or waited_ms >= wait_ms:
                return answer
            self._page.wait(POLL_INTERVAL_MS)
            waited_ms += POLL_INTERVAL_MS

    def _safe_screenshot(self) -> bytes | None:
        try:
            return self._page.screenshot()
        except Exception:
            # The screenshot is evidence for the step, not part of its verdict.
            logger.warning("user_journeys.run_screenshot_failed", exc_info=True)
            return None

    def _comparable_url(self) -> str:
        current = self._page.url
        if self._plan.base_origin is not None and origin_of(current) == self._plan.base_origin:
            return replace_origin(current, self._plan.recorded_origin)
        return current

    def _blocked_navigation(self) -> StepFailure | None:
        blocked = self._page.take_blocked_navigation()
        if blocked is None:
            return None
        return StepFailure(
            reason=JourneyStepFailureReason.NAVIGATION_BLOCKED,
            message=f"The page tried to open a URL that journey runs can't visit. {blocked.reason}",
        )


def _skipped(index: int) -> StepOutcome:
    return StepOutcome(
        index=index,
        status=JourneyRunStepStatus.SKIPPED,
        failure_reason=None,
        message="Skipped because an earlier step failed.",
        screenshot=None,
        duration_ms=None,
    )
