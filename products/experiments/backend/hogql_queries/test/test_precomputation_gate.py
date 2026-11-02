from datetime import UTC, datetime, timedelta

import time_machine

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentQuery, PrecomputationMode

from posthog.models.team.extensions import get_or_create_team_extension

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.facade.enums import PrecomputeSkipReason
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.exposures_precompute import ExposuresPrecompute
from products.experiments.backend.hogql_queries.precompute_policy import (
    MIN_PRECOMPUTATION_DURATION_SECONDS,
    experiment_has_min_runtime_for_precomputation,
    has_uncalculated_cohorts,
)
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


class TestPrecomputationDurationGate:
    @parameterized.expand(
        [
            # name, start_offset_seconds, end_offset_seconds (None = no end_date), expected
            ("no_start_date", None, None, False),
            ("draft_no_start", None, 7 * 24 * 3600, False),
            ("just_started_no_end", -60, None, False),
            ("six_hours_old_running", -6 * 3600, 7 * 24 * 3600, False),
            ("just_under_threshold_running", -(MIN_PRECOMPUTATION_DURATION_SECONDS - 60), None, False),
            ("at_threshold_running", -MIN_PRECOMPUTATION_DURATION_SECONDS, None, True),
            ("one_day_old_running", -24 * 3600, 7 * 24 * 3600, True),
            ("future_end_date_short_runtime", -3600, 30 * 24 * 3600, False),
            ("completed_short_in_past", -(8 * 24 * 3600), -(7 * 24 * 3600 + 23 * 3600), False),
            ("completed_long_in_past", -(8 * 24 * 3600), -(7 * 24 * 3600), True),
        ]
    )
    def test_gate(self, _name, start_offset_seconds, end_offset_seconds, expected):
        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
        start_date = None if start_offset_seconds is None else now + timedelta(seconds=start_offset_seconds)
        end_date = None if end_offset_seconds is None else now + timedelta(seconds=end_offset_seconds)

        with time_machine.travel(now, tick=False):
            assert experiment_has_min_runtime_for_precomputation(start_date, end_date) is expected


def _cohort_exposure_criteria(cohort_id: int) -> dict:
    return {
        "exposure_config": {
            "kind": "ExperimentEventExposureConfig",
            "event": "$feature_flag_called",
            "properties": [{"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}],
        }
    }


@override_settings(IN_UNIT_TESTING=True)
class TestUncalculatedCohortGate(ExperimentQueryRunnerBaseTest):
    @parameterized.expand(
        [
            # name, is_static, version, is_calculating, expected
            ("dynamic_never_calculated", False, None, True, True),
            ("dynamic_calculated", False, 1, False, False),
            ("dynamic_mid_recalculation", False, 3, True, False),
            ("static_populating", True, None, True, True),
            ("static_populated", True, None, False, False),
        ]
    )
    def test_cohort_states(self, _name, is_static, version, is_calculating, expected):
        cohort = Cohort.objects.create(team=self.team, name="test cohort", is_static=is_static)
        Cohort.objects.filter(pk=cohort.pk).update(version=version, is_calculating=is_calculating)

        assert has_uncalculated_cohorts(self.team, _cohort_exposure_criteria(cohort.pk)) is expected

    def test_no_cohort_references_returns_false(self):
        criteria = {
            "exposure_config": {
                "kind": "ExperimentEventExposureConfig",
                "event": "$feature_flag_called",
                "properties": [{"key": "email", "type": "person", "value": "@x.com", "operator": "icontains"}],
            }
        }
        assert has_uncalculated_cohorts(self.team, criteria, None) is False

    def test_finds_cohort_in_pydantic_metric(self):
        cohort = Cohort.objects.create(team=self.team, name="test cohort")
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", properties=[{"key": "id", "type": "cohort", "value": cohort.pk}])
        )
        assert has_uncalculated_cohorts(self.team, metric) is True

    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_exposures_precompute_waits_for_first_cohort_calculation(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2026, 4, 29, 0, 0, 0),  # over the duration threshold
        )
        cohort = Cohort.objects.create(team=self.team, name="fresh cohort", is_calculating=True)
        experiment.exposure_criteria = _cohort_exposure_criteria(cohort.pk)
        experiment.save()
        self._enable_precomputation()

        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)
        assert runner._exposures_precompute_applicable() is False
        assert runner._precompute_skip_reason() == "cohort_not_calculated"

        Cohort.objects.filter(pk=cohort.pk).update(version=1, is_calculating=False)
        assert runner._exposures_precompute_applicable() is True
        assert runner._precompute_skip_reason() is None


ACTIVATION_CRITERIA = {
    "activation_config": {"kind": "ExperimentEventExposureConfig", "event": "activated", "properties": []},
}

OLD_ENOUGH = datetime(2026, 4, 29, 0, 0, 0)
TOO_YOUNG = datetime(2026, 4, 30, 6, 0, 0)


@override_settings(IN_UNIT_TESTING=True)
@time_machine.travel("2026-04-30T12:00:00Z", tick=False)
class TestExposuresPrecompute(ExperimentQueryRunnerBaseTest):
    @parameterized.expand(
        [
            # name, start_date, team_enabled, criteria, mode, is_data_warehouse_query, group_type_index, reason, applicable
            ("eligible", OLD_ENOUGH, True, "none", None, False, None, None, True),
            (
                "precomputed_mode_skips_gates",
                TOO_YOUNG,
                False,
                "none",
                PrecomputationMode.PRECOMPUTED,
                False,
                None,
                None,
                True,
            ),
            (
                "direct_mode",
                OLD_ENOUGH,
                True,
                "none",
                PrecomputationMode.DIRECT,
                False,
                None,
                PrecomputeSkipReason.OVERRIDE_DIRECT,
                False,
            ),
            ("team_disabled", OLD_ENOUGH, False, "none", None, False, None, PrecomputeSkipReason.TEAM_DISABLED, False),
            ("below_min_runtime", TOO_YOUNG, True, "none", None, False, None, PrecomputeSkipReason.MIN_RUNTIME, False),
            (
                "activation_exposures",
                OLD_ENOUGH,
                True,
                "activation",
                None,
                False,
                None,
                PrecomputeSkipReason.ACTIVATION_CONFIG,
                False,
            ),
            (
                "uncalculated_cohort",
                OLD_ENOUGH,
                True,
                "uncalculated_cohort",
                None,
                False,
                None,
                PrecomputeSkipReason.COHORT_NOT_CALCULATED,
                False,
            ),
            ("data_warehouse", OLD_ENOUGH, True, "none", None, True, None, PrecomputeSkipReason.DATA_WAREHOUSE, False),
            (
                "group_aggregation",
                OLD_ENOUGH,
                True,
                "none",
                None,
                False,
                0,
                PrecomputeSkipReason.GROUP_AGGREGATION,
                False,
            ),
            (
                "precomputed_mode_with_data_warehouse",
                OLD_ENOUGH,
                True,
                "none",
                PrecomputationMode.PRECOMPUTED,
                True,
                None,
                None,
                False,
            ),
            (
                "precomputed_mode_with_group",
                OLD_ENOUGH,
                True,
                "none",
                PrecomputationMode.PRECOMPUTED,
                False,
                0,
                None,
                False,
            ),
        ]
    )
    def test_decisions(
        self,
        _name: str,
        start_date: datetime,
        team_enabled: bool,
        criteria: str,
        mode: PrecomputationMode | None,
        is_data_warehouse_query: bool,
        group_type_index: int | None,
        expected_reason: PrecomputeSkipReason | None,
        expected_applicable: bool,
    ) -> None:
        experiment = self.create_experiment(feature_flag=self.create_feature_flag(), start_date=start_date)
        if criteria == "activation":
            experiment.exposure_criteria = ACTIVATION_CRITERIA
        elif criteria == "uncalculated_cohort":
            cohort = Cohort.objects.create(team=self.team, name="fresh cohort", is_calculating=True)
            experiment.exposure_criteria = _cohort_exposure_criteria(cohort.pk)
        if team_enabled:
            self._enable_precomputation()
        else:
            self._disable_precomputation()

        precompute = ExposuresPrecompute(
            team=self.team,
            team_experiments_config=get_or_create_team_extension(self.team, TeamExperimentsConfig),
            experiment=experiment,
            window_start=experiment.start_date,
            window_end=datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
            exposure_criteria=experiment.exposure_criteria,
            cohort_filter_sources=(),
            precomputation_mode=mode,
            is_data_warehouse_query=is_data_warehouse_query,
            group_type_index=group_type_index,
        )

        assert precompute.ineligibility_reason() == expected_reason
        assert precompute.applicable is expected_applicable

    @parameterized.expand(
        [
            ("precomputed_mode_passes_through", TOO_YOUNG, PrecomputationMode.PRECOMPUTED, False, None, True),
            ("metric_cohorts_are_checked", OLD_ENOUGH, None, True, PrecomputeSkipReason.COHORT_NOT_CALCULATED, False),
        ]
    )
    def test_query_runner_wiring(
        self,
        _name: str,
        start_date: datetime,
        mode: PrecomputationMode | None,
        metric_has_uncalculated_cohort: bool,
        expected_reason: PrecomputeSkipReason | None,
        expected_applicable: bool,
    ) -> None:
        experiment = self.create_experiment(feature_flag=self.create_feature_flag(), start_date=start_date)
        self._enable_precomputation()
        properties = []
        if metric_has_uncalculated_cohort:
            cohort = Cohort.objects.create(team=self.team, name="fresh cohort", is_calculating=True)
            properties = [{"key": "id", "type": "cohort", "value": cohort.pk}]
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", properties=properties))
        query = ExperimentQuery(
            experiment_id=experiment.id, kind="ExperimentQuery", metric=metric, precomputation_mode=mode
        )
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert runner._precompute_skip_reason() == expected_reason
        assert runner._exposures_precompute_applicable() is expected_applicable
