from datetime import UTC, datetime
from typing import cast

from posthog.test.base import _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    IntervalType,
    StartHandling,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.exposure_query_logic import get_entity_key
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

DW_NODE = ExperimentDataWarehouseNode(
    table_name="usage",
    events_join_key="distinct_id",
    data_warehouse_join_key="userid",
    timestamp_field="ds",
)


def _retention_metric(
    start_event: EventsNode | ExperimentDataWarehouseNode | None = None,
    completion_event: EventsNode | ExperimentDataWarehouseNode | None = None,
    retention_window_end: int = 7,
    retention_window_unit: FunnelConversionWindowTimeUnit = FunnelConversionWindowTimeUnit.DAY,
    breakdown_filter: BreakdownFilter | None = None,
) -> ExperimentRetentionMetric:
    return ExperimentRetentionMetric(
        start_event=start_event or EventsNode(event="signup"),
        completion_event=completion_event or EventsNode(event="login"),
        retention_window_start=0,
        retention_window_end=retention_window_end,
        retention_window_unit=retention_window_unit,
        start_handling=StartHandling.FIRST_SEEN,
        breakdownFilter=breakdown_filter,
    )


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentRetentionMetricEventsPreaggregation(ExperimentQueryRunnerBaseTest):
    def _build_lazy_computation_builder(
        self, experiment, feature_flag, metric, as_of: datetime | None = None
    ) -> ExperimentQueryBuilder:
        exposure_params = get_exposure_config_params_for_builder(
            experiment.exposure_criteria, experiment.team, experiment.start_date
        )
        as_of = as_of if as_of is not None else datetime.now(UTC)
        date_range = experiment_window(experiment, self.team, as_of)
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=exposure_params.exposure_config,
            filter_test_accounts=exposure_params.filter_test_accounts,
            multiple_variant_handling=exposure_params.multiple_variant_handling,
            variants=[v["key"] for v in feature_flag.variants],
            date_range_query=QueryDateRange(
                date_range=date_range,
                team=self.team,
                interval=IntervalType.DAY,
                now=as_of,
            ),
            entity_key=get_entity_key(feature_flag.filters.get("aggregation_group_type_index")),
            metric=metric,
        )

    def _build_runner(self, experiment, metric: ExperimentRetentionMetric, as_of: datetime | None = None):
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        return ExperimentQueryRunner(query=query, team=self.team, as_of=as_of)

    def _create_exposure_event(self, distinct_id, feature_flag, variant, timestamp):
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                f"$feature/{feature_flag.key}": variant,
                "$feature_flag_response": variant,
                "$feature_flag": feature_flag.key,
            },
        )

    def test_precomputed_result_tolerates_replayed_build_rows(self):
        feature_flag = self.create_feature_flag(key="retention-metric-events-replay")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        metric = _retention_metric()
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Per variant: 3 exposed, 2 start, 1 completes within the window.
        for variant in ("control", "test"):
            for i in range(3):
                _create_person(distinct_ids=[f"{variant}_{i}"], team_id=self.team.pk)
                self._create_exposure_event(
                    f"{variant}_{i}", feature_flag, variant, datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
                )
                if i < 2:
                    _create_event(
                        team=self.team,
                        event="signup",
                        distinct_id=f"{variant}_{i}",
                        timestamp=datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
                    )
                if i < 1:
                    _create_event(
                        team=self.team,
                        event="login",
                        distinct_id=f"{variant}_{i}",
                        timestamp=datetime(2024, 1, 6, 12, 0, tzinfo=UTC),
                    )

        self._disable_precomputation()
        direct_runner = self._build_runner(experiment, metric)
        direct_result = cast(ExperimentQueryResponse, direct_runner.calculate())

        # First precomputed run builds the jobs whose rows the second run will re-read.
        self._enable_precomputation()
        first_runner = self._build_runner(experiment, metric)
        first_runner.calculate()
        assert first_runner._metric_events_precomputed is True

        # Simulate a replayed build INSERT: every stored metric-event row appears twice
        # under the same job. ReplacingMergeTree only collapses these at merge time, so
        # the retention aggregations (min/max/argMin/argMax start resolution, MAX(0/1)
        # outcome) must stay idempotent under duplicated rows — unlike mean, no dedup
        # CTE protects this read.
        table = SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()
        rows_before = sync_execute(
            f"SELECT count() FROM {table} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )[0][0]
        assert rows_before > 0
        sync_execute(
            f"INSERT INTO {table} SELECT * FROM {table} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )

        precomputed_runner = self._build_runner(experiment, metric)
        precomputed_result = cast(ExperimentQueryResponse, precomputed_runner.calculate())
        assert precomputed_runner._metric_events_precomputed is True

        assert direct_result.baseline is not None
        assert precomputed_result.baseline is not None
        assert precomputed_result.baseline.number_of_samples == direct_result.baseline.number_of_samples
        assert precomputed_result.baseline.sum == direct_result.baseline.sum
        assert direct_result.variant_results is not None
        assert precomputed_result.variant_results is not None
        assert precomputed_result.variant_results[0].sum == direct_result.variant_results[0].sum
        assert (
            precomputed_result.variant_results[0].number_of_samples
            == direct_result.variant_results[0].number_of_samples
        )

    @parameterized.expand(
        [
            ("direct", False),
            ("precomputed", True),
        ]
    )
    def test_completion_after_experiment_end_counts_on_both_paths(self, _name, use_precomputation):
        """
        A completion landing after the experiment end date (but inside the retention
        window) sits in the extension zone the build must cover: reverting the scan
        extension to conversion-window-only would silently drop it from the
        precomputed path while the direct scan keeps counting it. Week units also
        exercise the non-truncated window arithmetic on the preagg read bounds.
        """
        self._setup_precomputation_test(use_precomputation)
        feature_flag = self.create_feature_flag(key="retention-metric-events-extension")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )
        metric = _retention_metric(retention_window_end=1, retention_window_unit=FunnelConversionWindowTimeUnit.WEEK)
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()
        if use_precomputation:
            self._enable_precomputation()
        else:
            self._disable_precomputation()

        for variant in ("control", "test"):
            # retained: starts Jan 9, completes Jan 14 — 4 days after experiment end,
            # 5 days after start (inside the 1-week window)
            _create_person(distinct_ids=[f"{variant}_retained"], team_id=self.team.pk)
            self._create_exposure_event(
                f"{variant}_retained", feature_flag, variant, datetime(2024, 1, 8, 12, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"{variant}_retained",
                timestamp=datetime(2024, 1, 9, 12, 0, tzinfo=UTC),
            )
            _create_event(
                team=self.team,
                event="login",
                distinct_id=f"{variant}_retained",
                timestamp=datetime(2024, 1, 14, 12, 0, tzinfo=UTC),
            )
            # not retained: completion 8 days after start, outside the 1-week window
            _create_person(distinct_ids=[f"{variant}_late"], team_id=self.team.pk)
            self._create_exposure_event(
                f"{variant}_late", feature_flag, variant, datetime(2024, 1, 8, 12, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"{variant}_late",
                timestamp=datetime(2024, 1, 9, 12, 0, tzinfo=UTC),
            )
            _create_event(
                team=self.team,
                event="login",
                distinct_id=f"{variant}_late",
                timestamp=datetime(2024, 1, 17, 12, 0, tzinfo=UTC),
            )

        runner = self._build_runner(experiment, metric)
        result = cast(ExperimentQueryResponse, runner.calculate())
        assert runner._metric_events_precomputed is use_precomputation

        assert result.baseline is not None
        assert result.variant_results is not None
        # 2 starters per variant, exactly 1 retained
        assert result.baseline.number_of_samples == 2
        assert result.baseline.sum == 1
        assert result.variant_results[0].number_of_samples == 2
        assert result.variant_results[0].sum == 1

    @patch("products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute")
    def test_retention_metric_events_precomputation_hash_ignores_moving_experiment_end(self, mock_sync_execute):
        feature_flag = self.create_feature_flag(key="stable-retention-metric-events-hash")
        # Running experiment (no end_date) so the window end follows as_of. The retention
        # build query must keep the experiment date bounds as sentinel placeholders —
        # resolving them into the AST (e.g. via the direct-scan predicates) would change
        # the job hash on every load and silently defeat cache reuse.
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=None,
        )
        experiment.end_date = None
        experiment.save(update_fields=["end_date"])
        metric = _retention_metric()

        first_as_of = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)
        second_as_of = datetime(2024, 1, 5, 12, 30, tzinfo=UTC)

        first_result = self._build_runner(experiment, metric, as_of=first_as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, metric, as_of=first_as_of)
        )
        second_result = self._build_runner(experiment, metric, as_of=second_as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, metric, as_of=second_as_of)
        )

        assert first_result.ready is True
        assert second_result.ready is True
        assert first_result.job_ids == second_result.job_ids
        assert mock_sync_execute.call_count == len(first_result.job_ids)

    @patch("products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute")
    def test_retention_metric_events_precomputation_hash_tracks_retention_window(self, mock_sync_execute):
        feature_flag = self.create_feature_flag(key="retention-metric-events-hash-window")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
        )
        # retention_window_end enters the build query as a hashed constant (via the
        # window extension), not a sentinel: widening the window must invalidate the
        # cached jobs, or reads would keep serving a scan that stops too early.
        narrow_metric = _retention_metric(retention_window_end=7)
        wide_metric = _retention_metric(retention_window_end=14)
        as_of = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)

        first_narrow = self._build_runner(experiment, narrow_metric, as_of=as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, narrow_metric, as_of=as_of)
        )
        second_narrow = self._build_runner(experiment, narrow_metric, as_of=as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, narrow_metric, as_of=as_of)
        )
        wide = self._build_runner(experiment, wide_metric, as_of=as_of)._ensure_metric_events_precomputed(
            self._build_lazy_computation_builder(experiment, feature_flag, wide_metric, as_of=as_of)
        )

        assert first_narrow.job_ids == second_narrow.job_ids
        assert set(first_narrow.job_ids).isdisjoint(wide.job_ids)

    @parameterized.expand(
        [
            ("events_nodes", _retention_metric(), True),
            ("data_warehouse_start", _retention_metric(start_event=DW_NODE), False),
            ("data_warehouse_completion", _retention_metric(completion_event=DW_NODE), False),
            (
                "breakdown",
                _retention_metric(breakdown_filter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])),
                False,
            ),
            # retention_window_end is an unrestricted user input; an absurd window must
            # not stretch the precompute horizon into thousands of daily build jobs
            ("window_beyond_precompute_horizon", _retention_metric(retention_window_end=10_000), False),
        ]
    )
    def test_retention_metric_events_precompute_gate(self, _name, metric, applicable):
        feature_flag = self.create_feature_flag(key="retention-metric-events-gate")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        runner = self._build_runner(experiment, metric)

        with patch.object(ExperimentQueryRunner, "_retention_metric_events_precomputation_enabled", return_value=True):
            assert runner._metric_events_precompute_applicable() is applicable

    def test_retention_metric_events_precompute_disabled_without_flag(self):
        feature_flag = self.create_feature_flag(key="retention-metric-events-kill-switch")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        runner = self._build_runner(experiment, _retention_metric())

        # Fail-safe kill switch: with the flag absent/unevaluable, an otherwise
        # eligible retention metric must stay on the direct-scan path.
        assert runner._metric_events_precompute_applicable() is False
