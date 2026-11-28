import tempfile
from contextlib import ExitStack
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import (
    CreateJourneyInput,
    CreateJourneyRunInput,
    ElementClickStep,
    PageviewStep,
)
from products.user_journeys.backend.facade.enums import (
    JourneyRunStatus,
    JourneyRunStepStatus,
    JourneyStepFailureReason,
    JourneyVisualChange,
    UrlMatching,
)
from products.user_journeys.backend.logic import runs
from products.user_journeys.backend.logic.runs import RunRuntime
from products.user_journeys.backend.models import JourneyRun, JourneyRunStep
from products.user_journeys.backend.tests.journey_site import SiteVariant, serve_site
from products.user_journeys.backend.tests.run_runtime import (
    AllowLoopbackPolicy,
    MemoryScreenshotStore,
    local_chromium_page,
    local_runtime,
)


class _RefusePagesOn:
    def __init__(self, origin: str) -> None:
        self._origin = origin

    def page_error(self, url: str) -> str | None:
        return "Not an authorized URL." if url.startswith(self._origin) else None

    def request_error(self, url: str) -> str | None:
        return None


@patch("products.user_journeys.backend.logic.runs.is_user_journeys_enabled", return_value=True)
class TestJourneyRunsInBrowser(BaseTest):
    origins: dict[SiteVariant, str]
    _servers: ExitStack

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._servers = ExitStack()
        root = Path(cls._servers.enter_context(tempfile.TemporaryDirectory()))
        cls.origins = {variant: cls._servers.enter_context(serve_site(root, variant)) for variant in SiteVariant}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._servers.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.store = MemoryScreenshotStore()
        recorded = self.origins[SiteVariant.BASELINE]
        self.journey = api.create_journey(
            self.team.id,
            None,
            CreateJourneyInput(
                name="Sign up from the menu",
                steps=[
                    PageviewStep(url=f"{recorded}/index.html"),
                    ElementClickStep(selector="a.nav-signup", text="Sign up"),
                    PageviewStep(url="/signup.html", url_matching=UrlMatching.CONTAINS),
                    ElementClickStep(selector="#create-account", text="Create account"),
                ],
            ),
        )

    def _run(self, variant: SiteVariant) -> tuple[JourneyRun, list[JourneyRunStep]]:
        base_url = None if variant == SiteVariant.BASELINE else self.origins[variant]
        created = runs.create_run(
            self.team.id,
            CreateJourneyRunInput(journey_id=self.journey.id, base_url=base_url),
            url_policy=AllowLoopbackPolicy(),
        )
        run = runs.execute_run(self.team.id, created.id, runtime=local_runtime(self.store))
        return run, runs.get_run_steps(run)

    def test_menu_overflow_hides_the_sign_up_link_and_fails_the_run(self, _flag: MagicMock) -> None:
        baseline, baseline_steps = self._run(SiteVariant.BASELINE)
        assert baseline.status == JourneyRunStatus.PASSED, baseline.error
        assert [step.status for step in baseline_steps] == [JourneyRunStepStatus.PASSED] * 4
        assert {step.visual_change for step in baseline_steps} == {JourneyVisualChange.NEW}

        run, steps = self._run(SiteVariant.OVERFLOWING_MENU)

        assert run.status == JourneyRunStatus.FAILED
        assert run.baseline_run_id == baseline.id
        assert run.start_url == f"{self.origins[SiteVariant.OVERFLOWING_MENU]}/index.html"
        assert [step.status for step in steps] == [
            JourneyRunStepStatus.PASSED,
            JourneyRunStepStatus.FAILED,
            JourneyRunStepStatus.SKIPPED,
            JourneyRunStepStatus.SKIPPED,
        ]
        failing = steps[1]
        assert failing.failure_reason == JourneyStepFailureReason.ELEMENT_NOT_VISIBLE
        assert "cuts it off" in failing.message
        assert failing.screenshot_hash is not None
        assert failing.baseline_screenshot_hash == baseline_steps[1].screenshot_hash
        assert failing.visual_change == JourneyVisualChange.CHANGED
        assert steps[2].screenshot_hash is None

    @parameterized.expand(
        [
            (SiteVariant.HIDDEN_SIGN_UP, JourneyStepFailureReason.ELEMENT_NOT_VISIBLE),
            (SiteVariant.NO_SIGN_UP, JourneyStepFailureReason.ELEMENT_NOT_FOUND),
            (SiteVariant.COVERED_SIGN_UP, JourneyStepFailureReason.ELEMENT_OBSCURED),
        ]
    )
    def test_sign_up_link_failure_is_classified(
        self, _flag: MagicMock, variant: SiteVariant, reason: JourneyStepFailureReason
    ) -> None:
        run, steps = self._run(variant)

        assert run.status == JourneyRunStatus.FAILED
        assert steps[1].failure_reason == reason
        assert steps[1].screenshot_hash is not None
        assert [step.status for step in steps[2:]] == [JourneyRunStepStatus.SKIPPED] * 2

    def test_visual_change_passes_and_identical_rerun_is_unchanged(self, _flag: MagicMock) -> None:
        self._run(SiteVariant.BASELINE)
        rerun, rerun_steps = self._run(SiteVariant.BASELINE)
        recolored, recolored_steps = self._run(SiteVariant.RECOLORED_MENU)

        assert rerun.status == JourneyRunStatus.PASSED
        assert {step.visual_change for step in rerun_steps} == {JourneyVisualChange.UNCHANGED}
        assert recolored.status == JourneyRunStatus.PASSED
        assert recolored.baseline_run_id == rerun.id
        menu_page = recolored_steps[0]
        assert menu_page.visual_change == JourneyVisualChange.CHANGED
        assert menu_page.diff_percentage is not None and menu_page.diff_percentage > 0
        assert menu_page.diff_screenshot_hash is not None
        assert recolored_steps[2].visual_change == JourneyVisualChange.UNCHANGED

    def test_a_redirect_to_a_page_the_policy_refuses_is_blocked(self, _flag: MagicMock) -> None:
        refused = self.origins[SiteVariant.NO_SIGN_UP]
        start = f"{self.origins[SiteVariant.BASELINE]}/redirect?to={refused}/index.html"
        journey = api.create_journey(
            self.team.id,
            None,
            CreateJourneyInput(
                name="Open redirect",
                start_url=start,
                steps=[
                    PageviewStep(url="/index.html", url_matching=UrlMatching.CONTAINS),
                    ElementClickStep(selector="a.nav-item"),
                ],
            ),
        )
        created = runs.create_run(
            self.team.id, CreateJourneyRunInput(journey_id=journey.id), url_policy=AllowLoopbackPolicy()
        )
        runtime = RunRuntime(
            open_page=local_chromium_page, url_policy=lambda team_id: _RefusePagesOn(refused), store=self.store
        )

        run = runs.execute_run(self.team.id, created.id, runtime=runtime)

        steps = runs.get_run_steps(run)
        assert run.status == JourneyRunStatus.FAILED
        assert steps[0].failure_reason == JourneyStepFailureReason.NAVIGATION_BLOCKED
        assert "Not an authorized URL." in steps[0].message
