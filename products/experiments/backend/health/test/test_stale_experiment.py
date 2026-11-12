from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.facade.daily_calculation import (
    DAILY_CALCULATION_DAYS,
    daily_calculation_start_cutoff,
    is_past_daily_calculation,
)
from products.experiments.backend.health.checks.stale_experiment import stale_experiment
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckSkip,
    not_applicable,
)
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

STALE = ExperimentHealthFindingCode.STALE_EXPERIMENT
END = ExperimentHealthFindingActionKind.END_EXPERIMENT
FREEZE = ExperimentHealthFindingActionKind.FREEZE_EXPOSURE
PAST_THE_DAILY_CALCULATION: dict[str, Any] = {
    "past_daily_calculation": True,
    "hours_since_start": DAILY_CALCULATION_DAYS * 24 + 1,
}
NO_HISTORY = ExperimentHealthReaderAccess(
    can_read_flag_history=False,
    can_query_events=False,
    denied_event_properties=frozenset(),
    denied_person_properties=frozenset(),
    denied_group_properties=frozenset(),
)
READS_HISTORY = replace(NO_HISTORY, can_read_flag_history=True)
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


class TestStaleExperiment(TestCase):
    @parameterized.expand(
        [
            ("inside_the_daily_calculation", {}, None),
            ("past_the_daily_calculation", PAST_THE_DAILY_CALCULATION, STALE),
            ("paused", {**PAST_THE_DAILY_CALCULATION, "is_paused": True}, STALE),
            (
                "ended",
                {**PAST_THE_DAILY_CALCULATION, "is_running": False, "has_ended": True},
                not_applicable(NOT_AFTER_END),
            ),
            ("archived", {**PAST_THE_DAILY_CALCULATION, "archived": True}, not_applicable(NOT_ON_ARCHIVED)),
            (
                "draft",
                {"is_launched": False, "is_running": False, "hours_since_launch": None, "hours_since_start": None},
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
        outcome = stale_experiment(replace(RUNNING_CONTEXT, past_daily_calculation=True, hours_since_start=92.9 * 24))

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
            replace(RUNNING_CONTEXT, **PAST_THE_DAILY_CALCULATION, can_freeze_exposure=can_freeze_exposure)
        )

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual((outcome.severity, outcome.actions), (ExperimentHealthFindingSeverity.INFO, actions))
        self.assertEqual("freeze exposure" in outcome.detail, can_freeze_exposure)

    @parameterized.expand(
        [
            ("last_start_date_the_daily_jobs_keep", timedelta(0), False),
            ("one_second_earlier", timedelta(seconds=1), True),
        ]
    )
    def test_the_finding_starts_where_the_daily_calculation_stops(
        self, _name: str, before_cutoff: timedelta, expected: bool
    ) -> None:
        start_date = daily_calculation_start_cutoff(NOW) - before_cutoff

        self.assertEqual(is_past_daily_calculation(start_date, NOW), expected)


class TestStaleExperimentFromStoredExperiment(BaseTest):
    @parameterized.expand([("reads_history", READS_HISTORY), ("no_history", NO_HISTORY)])
    def test_counts_from_the_start_date_when_the_launch_came_later(
        self, _name: str, reader_access: ExperimentHealthReaderAccess
    ) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team, name="checkout", feature_flag=flag, start_date=timezone.now() - timedelta(days=90)
        )
        launched_at = timezone.now() - timedelta(days=10)
        ActivityLog.objects.create(
            team_id=self.team.id,
            scope="Experiment",
            item_id=str(experiment.id),
            activity="updated",
            detail={"changes": [{"field": "start_date", "before": None, "after": launched_at.isoformat()}]},
            created_at=launched_at,
        )

        health = get_experiment_health(
            team_id=self.team.id, experiment_id=experiment.id, reader_access=reader_access, user=self.user
        )

        finding = next(finding for finding in health.findings if finding.code == STALE)
        self.assertEqual(finding.evidence, {"days_running": 90})
