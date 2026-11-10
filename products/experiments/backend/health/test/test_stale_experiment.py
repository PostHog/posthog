from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.stale_experiment import stale_experiment
from products.experiments.backend.health.delays import DAILY_CALCULATION_DAYS
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckSkip,
    not_applicable,
)
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.temporal.scheduled_recalculation_logic import EXPERIMENT_RECALCULATION_MAX_AGE_DAYS

STALE = ExperimentHealthFindingCode.STALE_EXPERIMENT
END = ExperimentHealthFindingActionKind.END_EXPERIMENT
FREEZE = ExperimentHealthFindingActionKind.FREEZE_EXPOSURE
LAST_DAILY_RUN = {"hours_since_launch": DAILY_CALCULATION_DAYS * 24}
PAST_THE_LAST_RUN = {"hours_since_launch": DAILY_CALCULATION_DAYS * 24 + 1}


class TestStaleExperiment(TestCase):
    @parameterized.expand(
        [
            ("at_the_last_daily_run", LAST_DAILY_RUN, None),
            ("past_the_last_daily_run", PAST_THE_LAST_RUN, STALE),
            ("paused", {**PAST_THE_LAST_RUN, "is_paused": True}, STALE),
            (
                "ended",
                {**PAST_THE_LAST_RUN, "is_running": False, "has_ended": True},
                not_applicable(NOT_AFTER_END),
            ),
            ("archived", {**PAST_THE_LAST_RUN, "archived": True}, not_applicable(NOT_ON_ARCHIVED)),
            (
                "draft",
                {"is_launched": False, "is_running": False, "hours_since_launch": None},
                not_applicable(RUNS_AFTER_LAUNCH),
            ),
        ]
    )
    def test_stale_experiment(
        self, _name: str, changes: dict[str, Any], expected: ExperimentHealthFindingCode | CheckSkip | None
    ) -> None:
        outcome = stale_experiment(replace(RUNNING_CONTEXT, **changes))

        self.assertEqual(outcome.code if isinstance(outcome, ExperimentHealthFinding) else outcome, expected)

    def test_the_finding_counts_whole_days(self) -> None:
        outcome = stale_experiment(replace(RUNNING_CONTEXT, hours_since_launch=92.9 * 24))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(outcome.title, "This experiment has been running for 92 days")
        self.assertEqual(outcome.evidence, {"days_running": 92})

    @parameterized.expand(
        [
            ("can_freeze", True, (END, FREEZE)),
            ("cannot_freeze", False, (END,)),
        ]
    )
    def test_freeze_is_offered_only_where_it_can_run(
        self, _name: str, can_freeze_exposure: bool, actions: tuple[ExperimentHealthFindingActionKind, ...]
    ) -> None:
        outcome = stale_experiment(
            replace(
                RUNNING_CONTEXT,
                hours_since_launch=DAILY_CALCULATION_DAYS * 24 + 1,
                can_freeze_exposure=can_freeze_exposure,
            )
        )

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual((outcome.severity, outcome.actions), (ExperimentHealthFindingSeverity.INFO, actions))
        self.assertEqual("freeze exposure" in outcome.detail, can_freeze_exposure)

    def test_the_finding_starts_where_the_daily_calculation_stops(self) -> None:
        self.assertEqual(DAILY_CALCULATION_DAYS, EXPERIMENT_RECALCULATION_MAX_AGE_DAYS)
