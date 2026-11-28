from django.test import SimpleTestCase

from parameterized import parameterized

from products.user_journeys.backend.facade.contracts import ElementClickStep, JourneyStep, PageviewStep
from products.user_journeys.backend.facade.enums import JourneyRunStepStatus, JourneyStepFailureReason, UrlMatching
from products.user_journeys.backend.logic.run_browser import BlockedNavigation
from products.user_journeys.backend.logic.run_executor import (
    RUN_TIME_BUDGET_SECONDS,
    RunPlan,
    StepExecutor,
    url_matches,
)

PRODUCTION = "https://shop.example.com"
PREVIEW = "https://preview-42.example.net"
OK = {"status": "ok", "matches": 1, "index": 0, "x": 10, "y": 20}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakePage:
    """A page whose navigations and element verdicts are scripted by the test."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        redirects: dict[str, str] | None = None,
        verdicts: dict[str, dict] | None = None,
        click_targets: dict[tuple[float, float], str] | None = None,
        blocked_after_click: BlockedNavigation | None = None,
    ) -> None:
        self._clock = clock
        self._redirects = redirects or {}
        self._verdicts = verdicts or {}
        self._click_targets = click_targets or {}
        self._blocked_after_click = blocked_after_click
        self._blocked: BlockedNavigation | None = None
        self.url = "about:blank"
        self.opened: list[str] = []

    def goto(self, url: str, *, timeout_ms: int) -> int | None:
        self.opened.append(url)
        self.url = self._redirects.get(url, url)
        return 200

    def wait_for_settled(self, *, timeout_ms: int) -> None:
        pass

    def wait(self, ms: int) -> None:
        self._clock.now += ms / 1000

    def evaluate(self, script: str, arg: object) -> object:
        assert isinstance(arg, dict)
        return self._verdicts.get(arg["selector"], {"status": "not_found", "matches": 0})

    def screenshot(self) -> bytes | None:
        return b"png:" + self.url.encode()

    def click(self, x: float, y: float) -> None:
        self.url = self._click_targets.get((x, y), self.url)
        self._blocked = self._blocked_after_click

    def take_blocked_navigation(self) -> BlockedNavigation | None:
        blocked, self._blocked = self._blocked, None
        return blocked


def _plan(steps: list[JourneyStep], *, base_origin: str | None = None) -> RunPlan:
    origin = base_origin or PRODUCTION
    return RunPlan(steps=steps, start_url=f"{origin}/", recorded_origin=PRODUCTION, base_origin=base_origin)


class TestStepExecutor(SimpleTestCase):
    def test_login_redirect_fails_the_first_step_and_skips_the_rest(self) -> None:
        clock = FakeClock()
        page = FakePage(clock, redirects={f"{PRODUCTION}/": f"{PRODUCTION}/login?next=%2F"})
        steps: list[JourneyStep] = [
            PageviewStep(url=f"{PRODUCTION}/"),
            ElementClickStep(selector="a.pricing"),
            PageviewStep(url="/pricing", url_matching=UrlMatching.CONTAINS),
        ]

        outcomes = StepExecutor(page, _plan(steps), clock=clock).run()

        assert [o.status for o in outcomes] == [
            JourneyRunStepStatus.FAILED,
            JourneyRunStepStatus.SKIPPED,
            JourneyRunStepStatus.SKIPPED,
        ]
        assert outcomes[0].failure_reason == JourneyStepFailureReason.NAVIGATION_MISMATCH
        assert "/login?next=%2F" in outcomes[0].message
        assert outcomes[0].screenshot == f"png:{PRODUCTION}/login?next=%2F".encode()
        assert [o.screenshot for o in outcomes[1:]] == [None, None]

    def test_base_origin_runs_the_recorded_paths_on_the_other_origin(self) -> None:
        clock = FakeClock()
        page = FakePage(
            clock,
            verdicts={"a.pricing": OK},
            click_targets={(10.0, 20.0): f"{PREVIEW}/pricing?plan=team"},
        )
        steps: list[JourneyStep] = [
            PageviewStep(url=f"{PRODUCTION}/"),
            ElementClickStep(selector="a.pricing", url=f"{PRODUCTION}/"),
            PageviewStep(url=f"{PRODUCTION}/pricing?plan=team"),
        ]

        outcomes = StepExecutor(page, _plan(steps, base_origin=PREVIEW), clock=clock).run()

        assert page.opened == [f"{PREVIEW}/"]
        assert [o.status for o in outcomes] == [JourneyRunStepStatus.PASSED] * 3
        # The click step's screenshot is taken before the click moves the page on.
        assert outcomes[1].screenshot == f"png:{PREVIEW}/".encode()

    def test_navigation_the_policy_blocks_fails_the_click_step(self) -> None:
        clock = FakeClock()
        page = FakePage(
            clock,
            verdicts={"a.partner": OK},
            blocked_after_click=BlockedNavigation(url="https://elsewhere.example.org/", reason="Not authorized."),
        )
        steps: list[JourneyStep] = [PageviewStep(url=f"{PRODUCTION}/"), ElementClickStep(selector="a.partner")]

        outcomes = StepExecutor(page, _plan(steps), clock=clock).run()

        assert outcomes[1].failure_reason == JourneyStepFailureReason.NAVIGATION_BLOCKED
        assert "Not authorized." in outcomes[1].message

    def test_steps_past_the_run_budget_time_out(self) -> None:
        clock = FakeClock()
        page = FakePage(clock)
        steps: list[JourneyStep] = [PageviewStep(url=f"{PRODUCTION}/"), ElementClickStep(selector="a.missing")]
        executor = StepExecutor(page, _plan(steps), clock=clock)
        clock.now += RUN_TIME_BUDGET_SECONDS

        outcomes = executor.run()

        assert outcomes[0].failure_reason == JourneyStepFailureReason.TIMEOUT
        assert outcomes[1].status == JourneyRunStepStatus.SKIPPED

    def test_several_matches_are_noted_on_the_step(self) -> None:
        clock = FakeClock()
        page = FakePage(clock, verdicts={"a.nav": {**OK, "matches": 3}})
        steps: list[JourneyStep] = [PageviewStep(url=f"{PRODUCTION}/"), ElementClickStep(selector="a.nav")]

        outcomes = StepExecutor(page, _plan(steps), clock=clock).run()

        assert outcomes[1].status == JourneyRunStepStatus.PASSED
        assert outcomes[1].message == "3 elements match. The run used the first visible one."


class TestUrlMatches(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact_adds_root_slash", "https://a.example.com/", "https://a.example.com", UrlMatching.EXACT, True),
            ("exact_needs_query", "https://a.example.com/p?x=1", "https://a.example.com/p", UrlMatching.EXACT, False),
            ("contains_ignores_case", "https://a.example.com/Pricing", "/pricing", UrlMatching.CONTAINS, True),
            ("regex_searches", "https://a.example.com/p/42", r"/p/\d+$", UrlMatching.REGEX, True),
            ("invalid_regex_never_matches", "https://a.example.com/", "(?<=a)b", UrlMatching.REGEX, False),
        ]
    )
    def test_url_matches(self, _name: str, url: str, pattern: str, matching: UrlMatching, expected: bool) -> None:
        assert url_matches(url, pattern, matching) is expected
