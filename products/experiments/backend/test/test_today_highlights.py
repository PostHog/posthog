from datetime import UTC, date, datetime, time, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.experiments.backend import today_highlights
from products.experiments.backend.facade.contracts import (
    EndedExperiment,
    RunningExperiment,
    StoredArmResult,
    StoredPrimaryResult,
)
from products.experiments.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.today.backend.facade.contracts import HighlightExperimentResult, HighlightFindings
from products.today.backend.facade.testing import highlight_context

MONDAY = date(2026, 10, 12)
TUESDAY = date(2026, 10, 13)
NOW = datetime.combine(TUESDAY, time(12), tzinfo=UTC)
ENDED = EndedExperiment(id=7, name="Pricing page layout experiment", ended_at=NOW - timedelta(days=1))
RUNNING = RunningExperiment(
    id=9, name="Onboarding tips", started_at=NOW - timedelta(days=62), flag_key="onboarding-tips"
)
OWN = [
    RunningExperiment(id=id, name=name, started_at=NOW - timedelta(days=5), flag_key=f"flag-{id}")
    for id, name in ((11, "Checkout redesign experiment"), (12, "Pricing copy"), (13, "Signup flow"))
]


def stored(*variants: StoredArmResult, goal: str | None = None) -> StoredPrimaryResult:
    return StoredPrimaryResult(
        metric_name="Conversion rate",
        metric_type="funnel",
        proportion=True,
        goal=goal,
        baseline=StoredArmResult(key="control", number_of_samples=2000, mean=0.1),
        variants=variants,
    )


def arm(key: str, change: float | None, significant: bool | None = False) -> StoredArmResult:
    return StoredArmResult(key=key, number_of_samples=2100, mean=0.11, change=change, significant=significant)


@time_machine.travel(NOW, tick=False)
class TestExperiments(BaseTest):
    def _find(
        self,
        today: date,
        running: MagicMock,
        enrolled: MagicMock,
        results: MagicMock | None = None,
        hidden: frozenset[str] = frozenset(),
        source: str = "experiments",
    ) -> HighlightFindings:
        registered = next(s for s in HIGHLIGHT_SOURCES if s.name == source)
        context = highlight_context(team=self.team, user=self.user, today=today, hidden=hidden)
        with (
            patch.object(today_highlights, "list_ended_experiments_without_conclusion", return_value=[ENDED]),
            patch.object(today_highlights, "list_running_experiments", running),
            patch.object(today_highlights, "count_enrolled_people", enrolled),
            patch.object(today_highlights, "list_own_running_experiments", return_value=OWN),
            patch.object(today_highlights, "get_stored_primary_result", results or MagicMock(return_value=None)),
        ):
            return registered.find(context)

    @parameterized.expand(
        [
            (
                "a significant winner",
                stored(arm("test", 0.082, True)),
                8.2,
                HighlightExperimentResult("Conversion rate", "test", "control", 1, True, True, 4100),
            ),
            (
                "significance before size",
                stored(arm("bold", 0.2), arm("calm", 0.05, True)),
                5.0,
                HighlightExperimentResult("Conversion rate", "calm", "control", 2, True, True, 6200),
            ),
            (
                "the leader when nothing is significant",
                stored(arm("bold", -0.03), arm("calm", 0.04, None)),
                4.0,
                HighlightExperimentResult("Conversion rate", "calm", "control", 2, False, True, 6200),
            ),
            (
                "a metric that should decrease",
                stored(arm("test", -0.1, True), goal="decrease"),
                -10.0,
                HighlightExperimentResult("Conversion rate", "test", "control", 1, True, True, 4100),
            ),
            (
                "a loss",
                stored(arm("test", -0.06, True)),
                -6.0,
                HighlightExperimentResult("Conversion rate", "test", "control", 1, True, False, 4100),
            ),
            ("no change computed yet", stored(arm("test", None), arm("calm", None)), None, None),
        ]
    )
    def test_the_number_compares_the_variant_to_show_with_the_control(
        self,
        _name: str,
        result: StoredPrimaryResult,
        value: float | None,
        experiment: HighlightExperimentResult | None,
    ) -> None:
        found = self._find(
            TUESDAY,
            MagicMock(return_value=[]),
            MagicMock(return_value={}),
            MagicMock(return_value=result),
            source="experiment_numbers",
        )

        self.assertEqual(
            [(m.key, m.name, round(m.value, 6), m.url, m.reason, m.experiment) for m in found.pulse],
            [("experiment:11", "Checkout redesign", value, "/experiments/11", "experiment", experiment)]
            if experiment
            else [],
        )

    def test_the_number_skips_ignored_experiments_and_results_without_a_change(self) -> None:
        results = MagicMock(
            side_effect=lambda *, team_id, experiment_id: {12: stored(arm("test", None)), 13: stored(arm("test", 0.1))}[
                experiment_id
            ]
        )

        found = self._find(
            TUESDAY,
            MagicMock(return_value=[]),
            MagicMock(return_value={}),
            results,
            frozenset({"experiment:11"}),
            source="experiment_numbers",
        )

        self.assertEqual(
            ([m.key for m in found.pulse], [call.kwargs["experiment_id"] for call in results.call_args_list]),
            (["experiment:13"], [12, 13]),
        )

    def test_an_ended_experiment_without_a_decision_is_an_opportunity(self) -> None:
        found = self._find(TUESDAY, MagicMock(return_value=[]), MagicMock(return_value={}))

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
        found = self._find(
            TUESDAY, MagicMock(return_value=[RUNNING]), MagicMock(return_value={"onboarding-tips": enrolled})
        )

        self.assertEqual([c.title for c in found.items][1:], [title] if title else [])

    def test_only_experiment_keys_get_a_name(self) -> None:
        with patch.object(
            today_highlights, "viewable_experiment_names", return_value={11: "Checkout redesign experiment"}
        ) as names:
            named = today_highlights.name_experiment_numbers(
                self.team, self.user, ["experiment:11", "experiment:x", "signup_event"]
            )

        self.assertEqual(
            (named, names.call_args.kwargs["experiment_ids"]), ({"experiment:11": "Checkout redesign"}, {11})
        )

    def test_a_failed_count_keeps_the_ended_reminders(self) -> None:
        found = self._find(TUESDAY, MagicMock(return_value=[RUNNING]), MagicMock(side_effect=TimeoutError("slow")))

        self.assertEqual([c.key for c in found.items], ["experiment_ended:7"])
