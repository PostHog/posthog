import contextlib
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_GROUP_KEY,
    Experiment,
    ExperimentHoldout,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    EXPERIMENT_RECALCULATION_MAX_AGE_DAYS,
    MIN_EXPERIMENT_AGE,
    MIN_TIME_SINCE_LAST_RECALCULATION,
    SKIP_ACTIVE_RUN,
    SKIP_RECENT_RUN,
    count_total_exposures,
    find_scheduled_recalculation_candidates,
    recent_recalculation_skip,
    team_has_scheduled_recalculation_enabled,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _metric() -> dict[str, Any]:
    return {"kind": "ExperimentMetric", "metric_type": "mean", "uuid": str(uuid4())}


# Pinned at the default recalculation hour: a team with no config falls to hour 2, so a
# test that does not care about the hour still sees its experiments selected.
@time_machine.travel("2026-09-15T02:30:00Z", tick=False)
class TestScheduledRecalculationLogic(BaseTest):
    def _experiment(self, *, team: Team | None = None, started_hours_ago: float = 48, **overrides: Any) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team, key=f"flag-{uuid4()}", created_by=self.user, filters={"groups": []}
        )
        # No status here: save() always recomputes it from start_date and end_date.
        defaults: dict[str, Any] = {
            "team": team,
            "name": "exp",
            "feature_flag": flag,
            "start_date": timezone.now() - timedelta(hours=started_hours_ago),
            "metrics": [_metric()],
        }
        defaults.update(overrides)
        return Experiment.objects.create(**defaults)

    def _candidate_ids(self, hour: int | None = None) -> set[int]:
        # Discovery reads the hour from the clock, so a case that cares about the hour selects it
        # by travelling there. The minute stays at :30 so an age measured from the class instant
        # does not move.
        clock = (
            time_machine.travel(f"2026-09-15T{hour:02d}:30:00Z", tick=False)
            if hour is not None
            else contextlib.nullcontext()
        )
        with (
            clock,
            patch(
                "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
                return_value=True,
            ),
        ):
            return {c.experiment_id for c in find_scheduled_recalculation_candidates().candidates}

    def test_default_hour_picks_up_team_without_config(self):
        experiment = self._experiment()
        assert experiment.id in self._candidate_ids(2)
        assert experiment.id not in self._candidate_ids(5)

    def test_configured_hour_overrides_default(self):
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team,
            defaults={"experiment_recalculation_times": ["05:00:00"]},
        )
        experiment = self._experiment()
        assert experiment.id in self._candidate_ids(5)
        assert experiment.id not in self._candidate_ids(2)

    def test_both_configured_times_select_the_experiment(self):
        # Matching only the first entry would drop the team's second daily run.
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team,
            defaults={"experiment_recalculation_times": ["00:00:00", "12:00:00"]},
        )
        experiment = self._experiment()
        assert experiment.id in self._candidate_ids(0)
        assert experiment.id in self._candidate_ids(12)
        assert experiment.id not in self._candidate_ids(6)

    def test_a_team_with_no_configured_times_falls_to_the_default_hour(self):
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team,
            defaults={"experiment_recalculation_times": None},
        )
        experiment = self._experiment()
        assert experiment.id in self._candidate_ids(2)
        assert experiment.id not in self._candidate_ids(5)

    def test_deleted_experiment_is_excluded(self):
        experiment = self._experiment(deleted=True)
        assert experiment.id not in self._candidate_ids(2)

    @parameterized.expand(
        [
            ("draft", {"start_date": None}, Experiment.Status.DRAFT),
            ("stopped", {"end_date": timezone.now() - timedelta(hours=1)}, Experiment.Status.STOPPED),
        ]
    )
    def test_non_running_experiments_are_excluded(self, _name: str, overrides: dict[str, Any], expected_status: str):
        # save() recomputes status from the dates, so a status override would be silently ignored.
        experiment = self._experiment(**overrides)
        assert experiment.status == expected_status
        assert experiment.id not in self._candidate_ids(2)

    @parameterized.expand(
        [
            ("paused", False, False),
            ("active", True, True),
        ]
    )
    def test_a_paused_experiment_is_excluded(self, _name: str, flag_active: bool, expected: bool):
        # Pausing leaves status RUNNING and only deactivates the flag, so this is the one
        # exclusion the stored status cannot express.
        experiment = self._experiment()
        experiment.feature_flag.active = flag_active
        experiment.feature_flag.save()
        assert experiment.status == Experiment.Status.RUNNING
        assert (experiment.id in self._candidate_ids(2)) is expected

    def test_an_exposure_frozen_experiment_is_still_a_candidate(self):
        # Frozen exposure closes enrollment but metric events keep arriving, so the results
        # still move and the experiment stays worth recalculating.
        experiment = self._experiment()
        flag = experiment.feature_flag
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 100, EXPOSURE_FROZEN_GROUP_KEY: True}]}
        flag.save()
        experiment.refresh_from_db()
        assert experiment.is_exposure_frozen
        assert experiment.id in self._candidate_ids(2)

    @parameterized.expand(
        [
            ("too_new", 3, False),
            ("just_old_enough", 13, True),
            ("too_old", 24 * 61, False),
            ("min_age_boundary", MIN_EXPERIMENT_AGE.total_seconds() / 3600, True),
            ("max_age_boundary", EXPERIMENT_RECALCULATION_MAX_AGE_DAYS * 24, True),
        ]
    )
    def test_age_bounds(self, _name: str, started_hours_ago: float, expected: bool):
        # The boundary cases sit on the inclusive edge, so the fixture and the filter must
        # read the same instant or they fall a hair outside it. The class-level clock pin
        # guarantees that.
        experiment = self._experiment(started_hours_ago=started_hours_ago)
        assert (experiment.id in self._candidate_ids()) is expected

    def test_experiment_without_metrics_is_a_candidate(self):
        experiment = self._experiment(metrics=[])
        assert experiment.id in self._candidate_ids(2)

    def test_feature_flag_off_yields_no_candidates(self):
        self._experiment()
        with patch(
            "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
            return_value=False,
        ):
            assert find_scheduled_recalculation_candidates().candidates == []

    def test_flag_is_evaluated_once_per_team(self):
        for _ in range(3):
            self._experiment()
        with patch(
            "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
            return_value=True,
        ) as flag:
            find_scheduled_recalculation_candidates()
        assert flag.call_count == 1

    def test_no_recalculations_means_no_skip(self):
        experiment = self._experiment()
        assert recent_recalculation_skip(experiment, self.team.id) is None

    @parameterized.expand(
        [
            ("pending", ExperimentMetricsRecalculation.Status.PENDING, ExperimentMetricsRecalculation.Trigger.MANUAL),
            (
                "in_progress",
                ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                ExperimentMetricsRecalculation.Trigger.MANUAL,
            ),
            (
                # Excluded from the freshness check, but an in-flight sync run still blocks a start.
                "pending_timeseries_sync",
                ExperimentMetricsRecalculation.Status.PENDING,
                ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC,
            ),
        ]
    )
    def test_active_run_skips(self, _name: str, status: str, trigger: str):
        experiment = self._experiment()
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team, experiment=experiment, status=status, trigger=trigger, started_at=timezone.now()
            )
        decision = recent_recalculation_skip(experiment, self.team.id)
        assert decision is not None
        assert decision.reason == SKIP_ACTIVE_RUN

    @parameterized.expand(
        [
            ("pending", ExperimentMetricsRecalculation.Status.PENDING),
            ("in_progress", ExperimentMetricsRecalculation.Status.IN_PROGRESS),
        ]
    )
    def test_stale_active_run_does_not_skip(self, _name: str, status: str):
        # Nothing reaps an abandoned row, so an unbounded active check would lock the experiment out.
        experiment = self._experiment()
        stale = timezone.now() - timedelta(days=5)
        with team_scope(self.team.id, canonical=True):
            recalc = ExperimentMetricsRecalculation.objects.create(
                team=self.team, experiment=experiment, status=status, started_at=stale
            )
            ExperimentMetricsRecalculation.objects.filter(id=recalc.id).update(created_at=stale)
        assert recent_recalculation_skip(experiment, self.team.id) is None

    def test_recent_completed_run_skips(self):
        experiment = self._experiment()
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                completed_at=timezone.now() - timedelta(minutes=10),
            )
        decision = recent_recalculation_skip(experiment, self.team.id)
        assert decision is not None
        assert decision.reason == SKIP_RECENT_RUN
        assert decision.detail["minutes_since_completion"] == 10

    def test_old_completed_run_does_not_skip(self):
        experiment = self._experiment()
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                completed_at=timezone.now() - MIN_TIME_SINCE_LAST_RECALCULATION - timedelta(minutes=1),
            )
        assert recent_recalculation_skip(experiment, self.team.id) is None

    def test_recent_timeseries_sync_run_is_ignored(self):
        # A sync row published at :00 is always fresher than the limit, so counting it
        # would stop every :30 run.
        experiment = self._experiment()
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.COMPLETED,
                trigger=ExperimentMetricsRecalculation.Trigger.TIMESERIES_SYNC,
                completed_at=timezone.now() - timedelta(minutes=5),
            )
        assert recent_recalculation_skip(experiment, self.team.id) is None

    def test_unfinished_failed_run_is_ignored(self):
        experiment = self._experiment()
        with team_scope(self.team.id, canonical=True):
            ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.FAILED,
                completed_at=None,
            )
        assert recent_recalculation_skip(experiment, self.team.id) is None

    def test_flag_helper_passes_group_properties(self):
        with patch(
            "products.experiments.backend.temporal.scheduled_recalculation_logic.feature_enabled_or_false",
            return_value=True,
        ) as flag:
            assert team_has_scheduled_recalculation_enabled(self.team.id, str(self.team.organization_id)) is True
        assert flag.call_args.kwargs["groups"]["organization"] == str(self.team.organization_id)
        assert flag.call_args.kwargs["only_evaluate_locally"] is True

    def test_exposure_count_sums_variants_and_drops_the_multiple_bucket(self):
        # $multiple holds entities that saw more than one variant, so it is not a variant's
        # audience and must not count toward the threshold.
        experiment = self._experiment()
        response = SimpleNamespace(total_exposures={"control": 40, "test": 35, MULTIPLE_VARIANT_KEY: 500})
        runner = MagicMock()
        runner.run.return_value = response
        with patch(
            "products.experiments.backend.hogql_queries.experiment_exposures_query_runner.ExperimentExposuresQueryRunner",
            return_value=runner,
        ):
            assert count_total_exposures(experiment) == 75

    def test_exposure_count_is_zero_when_the_runner_returns_nothing(self):
        experiment = self._experiment()
        runner = MagicMock()
        runner.run.return_value = SimpleNamespace(total_exposures=None)
        with patch(
            "products.experiments.backend.hogql_queries.experiment_exposures_query_runner.ExperimentExposuresQueryRunner",
            return_value=runner,
        ):
            assert count_total_exposures(experiment) == 0

    def test_exposure_count_serializes_a_holdout(self):
        # The FK gives a model instance and the query field is a pydantic type, so passing the
        # instance through raises inside the runner and the experiment reads as query-failed.
        holdout = ExperimentHoldout.objects.create(team=self.team, name="h", filters=[])
        experiment = self._experiment(holdout=holdout)
        runner = MagicMock()
        runner.run.return_value = SimpleNamespace(total_exposures={"control": 10, "test": 10})
        with patch(
            "products.experiments.backend.hogql_queries.experiment_exposures_query_runner.ExperimentExposuresQueryRunner",
            return_value=runner,
        ) as runner_class:
            assert count_total_exposures(experiment) == 20
        assert runner_class.call_args.kwargs["query"].holdout.id == holdout.id
