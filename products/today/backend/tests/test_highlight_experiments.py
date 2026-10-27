from datetime import UTC, date, datetime, time, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.experiments.backend.facade.contracts import EndedExperiment, RunningExperiment
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import experiments
from products.today.backend.logic.highlight_types import Context, Found

MONDAY = date(2026, 10, 12)
TUESDAY = date(2026, 10, 13)
NOW = datetime.combine(TUESDAY, time(12), tzinfo=UTC)
ENDED = EndedExperiment(id=7, name="Pricing page layout experiment", ended_at=NOW - timedelta(days=1))
RUNNING = RunningExperiment(
    id=9, name="Onboarding tips", started_at=NOW - timedelta(days=62), flag_key="onboarding-tips"
)


@time_machine.travel(NOW, tick=False)
class TestExperiments(BaseTest):
    def _find(self, today: date, running: MagicMock, enrolled: MagicMock) -> tuple[Found, Context]:
        registered = next(s for s in load_sources() if s.name == "experiments")
        context = Context(self.team, self.user, today)
        with (
            patch.object(experiments, "list_ended_experiments_without_conclusion", return_value=[ENDED]),
            patch.object(experiments, "list_running_experiments", running),
            patch.object(experiments, "count_enrolled_people", enrolled),
        ):
            return registered.find(context), context

    def test_an_ended_experiment_without_a_decision_is_an_opportunity(self) -> None:
        found, _ = self._find(TUESDAY, MagicMock(return_value=[]), MagicMock(return_value={}))

        self.assertEqual(
            [(c.title, c.detail, c.url) for c in found.items],
            [
                (
                    "Experiment ‘Pricing page layout’ ended yesterday",
                    "Read the results and decide whether to release the change",
                    "/experiments/7",
                )
            ],
        )

    @parameterized.expand([("Monday", MONDAY, None), ("Tuesday", TUESDAY, NOW - timedelta(days=67))])
    def test_only_mondays_look_past_the_week_an_experiment_crosses_60_days(
        self, _name: str, today: date, started_after: datetime | None
    ) -> None:
        running = MagicMock(return_value=[])

        self._find(today, running, MagicMock(return_value={}))

        self.assertEqual(
            (running.call_args.kwargs["started_after"], running.call_args.kwargs["started_before"]),
            (started_after, NOW - timedelta(days=60)),
        )

    @parameterized.expand(
        [
            ("few users", 42, "Experiment ‘Onboarding tips’ reached 42 users in the last 14 days"),
            ("one user", 1, "Experiment ‘Onboarding tips’ reached 1 user in the last 14 days"),
            ("no users", 0, "Experiment ‘Onboarding tips’ reached no users in the last 14 days"),
            ("enough users", 150, None),
        ]
    )
    def test_a_long_running_experiment_with_few_users_is_a_risk(
        self, _name: str, enrolled: int, title: str | None
    ) -> None:
        found, _ = self._find(
            TUESDAY, MagicMock(return_value=[RUNNING]), MagicMock(return_value={"onboarding-tips": enrolled})
        )

        self.assertEqual([c.title for c in found.items][1:], [title] if title else [])

    def test_a_failed_count_keeps_the_ended_reminders(self) -> None:
        found, context = self._find(
            TUESDAY, MagicMock(return_value=[RUNNING]), MagicMock(side_effect=TimeoutError("slow"))
        )

        self.assertEqual(
            ([c.key for c in found.items], context.failures), (["experiment_ended:7"], ["experiments_enrolled"])
        )
