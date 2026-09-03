import uuid
from datetime import timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.temporal.enrollment_census_logic import (
    BUILD_CAP_EXCLUSION_BYTES,
    EXCLUSION_BUILD_BYTE_CAP,
    MAX_ENROLLMENTS_PER_RUN,
    EnrollmentCensusReport,
    TeamDirectScanStats,
    TeamRunningLoad,
    build_census_report,
    enroll_candidates,
    run_enrollment_census_sync,
    running_experiment_load,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _stats(**overrides: Any) -> TeamDirectScanStats:
    defaults: dict[str, Any] = {
        "team_id": 1,
        "direct_reads": 100,
        "slow_reads": 0,
        "max_read_bytes": 10**9,
        "total_read_bytes": 10**11,
        "hard_failures": 0,
        "experiment_count": 3,
    }
    defaults.update(overrides)
    return TeamDirectScanStats(**defaults)


class TestEnrollmentCensusCriteria(BaseTest):
    @parameterized.expand(
        [
            ("scan_volume", _stats(total_read_bytes=6 * 10**12), ("scan_volume",)),
            ("slow_read_fraction", _stats(slow_reads=11), ("slow_reads",)),
            ("hard_failures", _stats(hard_failures=5), ("hard_failures",)),
            ("below_all_thresholds", _stats(slow_reads=10, hard_failures=4), ()),
            ("too_few_reads", _stats(direct_reads=49, slow_reads=49, total_read_bytes=6 * 10**12), ()),
        ]
    )
    def test_candidate_criteria(
        self, _name: str, stats: TeamDirectScanStats, expected_reasons: tuple[str, ...]
    ) -> None:
        report = build_census_report([stats], window_days=14)
        if expected_reasons:
            assert len(report.candidates) == 1
            assert report.candidates[0].reasons == expected_reasons
        else:
            assert report.candidates == ()
        assert report.excluded == ()

    def test_build_cap_team_is_excluded_not_enrolled(self) -> None:
        stats = _stats(total_read_bytes=50 * 10**12, max_read_bytes=BUILD_CAP_EXCLUSION_BYTES + 1)
        report = build_census_report([stats], window_days=14)
        assert report.candidates == ()
        assert len(report.excluded) == 1
        assert report.excluded[0].reason == EXCLUSION_BUILD_BYTE_CAP

    def test_candidates_ordered_by_total_bytes_descending(self) -> None:
        small = _stats(team_id=1, total_read_bytes=6 * 10**12)
        large = _stats(team_id=2, total_read_bytes=9 * 10**12)
        report = build_census_report([small, large], window_days=14)
        assert [candidate.stats.team_id for candidate in report.candidates] == [2, 1]

    @freeze_time("2026-01-15")
    def test_build_load_counts_running_experiments_and_all_metric_kinds(self) -> None:
        def _experiment(metrics: list[dict], **kwargs: Any) -> Experiment:
            return Experiment.objects.create(
                team=self.team,
                created_by=self.user,
                feature_flag=FeatureFlag.objects.create(
                    team=self.team, created_by=self.user, key=f"flag-{uuid.uuid4().hex[:8]}"
                ),
                name="exp",
                metrics=metrics,
                start_date=timezone.now() - timedelta(days=3),
                **kwargs,
            )

        running = _experiment(
            metrics=[{"kind": "ExperimentMetric"}] * 2, metrics_secondary=[{"kind": "ExperimentMetric"}]
        )
        saved = ExperimentSavedMetric.objects.create(
            team=self.team, name="saved", query={"kind": "ExperimentMetric", "metric_type": "funnel"}
        )
        ExperimentToSavedMetric.objects.create(experiment=running, saved_metric=saved, metadata={"type": "primary"})
        _experiment(metrics=[{"kind": "ExperimentMetric"}], end_date=timezone.now())
        _experiment(metrics=[{"kind": "ExperimentMetric"}], deleted=True)

        assert running_experiment_load([self.team.id]) == {
            self.team.id: TeamRunningLoad(running_experiments=1, running_metrics=4)
        }


class TestEnrollmentWrites(BaseTest):
    def _team(self) -> Team:
        return Team.objects.create(organization=self.organization, name=f"team-{uuid.uuid4().hex[:8]}")

    def _report_for(self, teams: list[Team]) -> EnrollmentCensusReport:
        # Descending bytes in list order, matching the census sort.
        stats = [
            _stats(team_id=team.id, total_read_bytes=(len(teams) - i + 5) * 10**12) for i, team in enumerate(teams)
        ]
        return build_census_report(stats, window_days=14)

    def test_enrolls_worst_first_up_to_cap(self):
        teams = [self._team() for _ in range(MAX_ENROLLMENTS_PER_RUN + 2)]
        report = self._report_for(teams)

        enrolled = enroll_candidates(report)

        assert enrolled == [team.id for team in teams[:MAX_ENROLLMENTS_PER_RUN]]
        for team in teams[:MAX_ENROLLMENTS_PER_RUN]:
            config = TeamExperimentsConfig.objects.get(team=team)
            assert config.experiment_precomputation_enabled
            assert config.precomputation_enabled_set_by == TeamExperimentsConfig.PrecomputationEnabledSetBy.AUTO
        for team in teams[MAX_ENROLLMENTS_PER_RUN:]:
            assert not TeamExperimentsConfig.objects.filter(team=team, experiment_precomputation_enabled=True).exists()

    def test_never_overrides_a_human_and_skips_enabled_without_burning_cap(self):
        manually_disabled, already_enabled, fresh = self._team(), self._team(), self._team()
        TeamExperimentsConfig.objects.update_or_create(
            team=manually_disabled,
            defaults={
                "experiment_precomputation_enabled": False,
                "precomputation_enabled_set_by": TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL,
            },
        )
        TeamExperimentsConfig.objects.update_or_create(
            team=already_enabled,
            defaults={
                "experiment_precomputation_enabled": True,
                "precomputation_enabled_set_by": TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL,
            },
        )
        report = self._report_for([manually_disabled, already_enabled, fresh])

        enrolled = enroll_candidates(report)

        assert enrolled == [fresh.id]
        config = TeamExperimentsConfig.objects.get(team=manually_disabled)
        assert not config.experiment_precomputation_enabled
        assert config.precomputation_enabled_set_by == TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL

    @parameterized.expand([("report_only", "report_only", False), ("enroll", "enroll", True)])
    def test_mode_gates_the_write(self, _name: str, mode: str, expect_write: bool):
        team = self._team()
        row = (team.id, 100, 0, 10**9, 6 * 10**12, 0, 3)
        with (
            override_settings(EXPERIMENT_PRECOMPUTE_ENROLLMENT_MODE=mode),
            patch(
                "products.experiments.backend.temporal.enrollment_census_logic.sync_execute",
                return_value=[row],
            ),
        ):
            run_enrollment_census_sync()

        enabled = TeamExperimentsConfig.objects.filter(team=team, experiment_precomputation_enabled=True).exists()
        assert enabled == expect_write

    def test_deleted_team_is_skipped_and_later_candidates_still_enroll(self):
        fresh = self._team()
        deleted_team_stats = _stats(team_id=999_999_999, total_read_bytes=9 * 10**12)
        fresh_stats = _stats(team_id=fresh.id, total_read_bytes=6 * 10**12)
        report = build_census_report([deleted_team_stats, fresh_stats], window_days=14)

        enrolled = enroll_candidates(report)

        assert enrolled == [fresh.id]
