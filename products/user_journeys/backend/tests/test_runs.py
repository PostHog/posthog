from contextlib import AbstractContextManager
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import (
    CreateJourneyInput,
    CreateJourneyRunInput,
    ElementClickStep,
    JourneyRunInProgressError,
    PageviewStep,
)
from products.user_journeys.backend.facade.enums import JourneyRunStatus
from products.user_journeys.backend.logic import runs
from products.user_journeys.backend.logic.run_browser import BrowserOptions, BrowserPage, BrowserUnavailableError
from products.user_journeys.backend.logic.run_urls import UrlPolicy
from products.user_journeys.backend.tests.run_runtime import AllowLoopbackPolicy, MemoryScreenshotStore


class _FailingBrowser(AbstractContextManager[BrowserPage]):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __enter__(self) -> BrowserPage:
        raise self._error

    def __exit__(self, *exc_info: object) -> None:
        pass


def _runtime_failing_with(error: Exception) -> runs.RunRuntime:
    def open_page(options: BrowserOptions, policy: UrlPolicy) -> AbstractContextManager[BrowserPage]:
        return _FailingBrowser(error)

    return runs.RunRuntime(
        open_page=open_page, url_policy=lambda team_id: AllowLoopbackPolicy(), store=MemoryScreenshotStore()
    )


@patch("products.user_journeys.backend.logic.runs.is_user_journeys_enabled", return_value=True)
class TestJourneyRunLifecycle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.journey = api.create_journey(
            self.team.id,
            None,
            CreateJourneyInput(
                name="Checkout",
                steps=[PageviewStep(url="https://shop.example.com/cart"), ElementClickStep(selector="#pay")],
            ),
        )

    def _create(self) -> runs.JourneyRun:
        return runs.create_run(
            self.team.id, CreateJourneyRunInput(journey_id=self.journey.id), url_policy=AllowLoopbackPolicy()
        )

    @parameterized.expand(
        [
            ("browser_unavailable", BrowserUnavailableError("All browsers are busy."), "All browsers are busy."),
            ("crash", RuntimeError("boom"), "The run stopped because of an unexpected error. Start it again."),
        ]
    )
    def test_a_run_that_cannot_finish_ends_errored_and_frees_the_journey(
        self, _flag: MagicMock, _name: str, error: Exception, message: str
    ) -> None:
        run = runs.execute_run(self.team.id, self._create().id, runtime=_runtime_failing_with(error))

        assert run.status == JourneyRunStatus.ERRORED
        assert run.error == message
        assert run.finished_at is not None
        assert self._create().status == JourneyRunStatus.PENDING

    def test_executing_a_run_that_is_not_pending_does_nothing(self, _flag: MagicMock) -> None:
        run = runs.execute_run(
            self.team.id, self._create().id, runtime=_runtime_failing_with(BrowserUnavailableError("busy"))
        )
        retry_runtime = _runtime_failing_with(RuntimeError("must not open a browser"))

        again = runs.execute_run(self.team.id, run.id, runtime=retry_runtime)

        assert again.status == JourneyRunStatus.ERRORED
        assert again.error == "busy"

    def test_a_second_run_waits_for_the_first_unless_the_first_is_stuck(self, _flag: MagicMock) -> None:
        first = self._create()
        with self.assertRaises(JourneyRunInProgressError):
            self._create()

        with time_machine.travel(first.created_at + runs.PENDING_STALE_AFTER + timedelta(minutes=1), tick=False):
            second = self._create()

        first.refresh_from_db()
        assert first.status == JourneyRunStatus.ERRORED
        assert first.error == "The run never started. Start it again."
        assert second.status == JourneyRunStatus.PENDING
