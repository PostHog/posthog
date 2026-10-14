from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentExposureQuery,
    ExperimentFunnelsQuery,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentTrendsQuery,
    FunnelsQuery,
    HogQLQueryModifiers,
    PrecomputationMode,
    TrendsQuery,
)

from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner, get_query_runner
from posthog.models.event.new_events_schema import get_new_events_cluster_host, new_events_cluster_host_scope
from posthog.models.instance_setting import override_instance_config
from posthog.models.team.extensions import get_or_create_team_extension

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.experiments.backend.hogql_queries.experiment_funnels_query_runner import ExperimentFunnelsQueryRunner
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.experiment_trends_query_runner import ExperimentTrendsQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentQueryRunnerSingleFlight(APIBaseTest):
    def setUp(self):
        super().setUp()
        feature_flag = self.feature_flag = FeatureFlag.objects.create(
            name="Test flag",
            key="test-flag",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "control", "rollout_percentage": 50},
                        {"key": "test", "name": "test", "rollout_percentage": 50},
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = self.experiment = Experiment.objects.create(
            name="test-experiment", team=self.team, feature_flag=feature_flag
        )
        self.query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL)),
        )

    @parameterized.expand(
        [
            ("as_of", {"as_of": datetime(2026, 1, 1, tzinfo=UTC)}),
            ("bypass_warehouse_access_control", {"bypass_warehouse_access_control": True}),
            ("max_execution_time", {"max_execution_time": 30}),
        ]
    )
    def test_recalculation_does_not_pair_with_a_results_request(self, _name, recalculation_kwargs):
        results_request = ExperimentQueryRunner(query=self.query, team=self.team)
        recalculation = ExperimentQueryRunner(query=self.query, team=self.team, **recalculation_kwargs)
        assert (recalculation.get_cache_key(), recalculation.single_flight_variant()) != (
            results_request.get_cache_key(),
            results_request.single_flight_variant(),
        )

    @parameterized.expand(
        [
            (kind, native, existing_jobs)
            for kind in ("metric", "exposures")
            for native, existing_jobs in ((False, False), (True, False), (True, True))
        ]
    )
    @override_settings(
        IN_UNIT_TESTING=True,
        CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False,
        CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com",
    )
    def test_experiment_execution_preserves_selected_table_and_debug_sql(
        self, kind: str, native: bool, existing_jobs: bool
    ) -> None:
        experiment, flag = self.experiment, self.feature_flag
        experiment.start_date = datetime(2024, 1, 1, tzinfo=UTC)
        experiment.end_date = datetime(2024, 1, 7, tzinfo=UTC)
        experiment.save(update_fields=["start_date", "end_date"])
        assert experiment.start_date is not None and experiment.end_date is not None
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.experiment_precomputation_enabled = True
        config.save()
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"))
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]))
        modifiers = HogQLQueryModifiers(useNewEventsSchema=native, useNewEventsCluster=native)
        runner: ExperimentQueryRunner | ExperimentExposuresQueryRunner
        if kind == "metric":
            runner = ExperimentQueryRunner(
                query=self.query.model_copy(update={"precomputation_mode": PrecomputationMode.PRECOMPUTED}),
                team=self.team,
                user=self.user,
                modifiers=modifiers,
            )
        else:
            runner = ExperimentExposuresQueryRunner(
                query=ExperimentExposureQuery(
                    experiment_id=experiment.id,
                    experiment_name=experiment.name,
                    feature_flag={"key": flag.key},
                    start_date=experiment.start_date.isoformat(),
                    end_date=experiment.end_date.isoformat(),
                ),
                team=self.team,
                user=self.user,
                modifiers=modifiers,
            )
        if existing_jobs:
            seed = get_query_runner(
                runner.query,
                self.team,
                user=self.user,
                modifiers=HogQLQueryModifiers(useNewEventsSchema=False, useNewEventsCluster=False),
            )
            assert isinstance(seed, (ExperimentQueryRunner, ExperimentExposuresQueryRunner))
            with patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                return_value=0,
            ):
                if isinstance(seed, ExperimentQueryRunner):
                    seed._get_experiment_query()
                else:
                    seed._get_exposure_query()
            self.assertTrue(
                PreaggregationJob.objects.filter(team=self.team, status=PreaggregationJob.Status.READY).exists()
            )
        job_count = PreaggregationJob.objects.filter(team=self.team).count()
        cache_key = runner.get_cache_key()
        with (
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                return_value=0,
            ) as insert,
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute,
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            if kind == "metric":
                assert isinstance(runner, ExperimentQueryRunner)
                runner._evaluate_experiment_query()
            else:
                assert isinstance(runner, ExperimentExposuresQueryRunner)
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)
            enqueue.assert_not_called()
        if native:
            insert.assert_not_called()
            self.assertEqual(PreaggregationJob.objects.filter(team=self.team).count(), job_count)
            self.assertNotIn("preaggregated", execute.call_args.args[0])
        self.assertEqual("events_json" in execute.call_args.args[0], native)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NEW_EVENTS_CLUSTER, native)
        self.assertEqual(runner.get_cache_key(), cache_key)
        if kind == "metric":
            assert isinstance(runner, ExperimentQueryRunner)
            assert runner.clickhouse_sql is not None
            self.assertEqual("events_json" in runner.clickhouse_sql, native)

    @parameterized.expand(
        [
            (kind, native, child_opt_in)
            for kind in ("trends", "funnels")
            for native, child_opt_in in ((False, False), (True, False), (True, True), (False, True))
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_legacy_experiment_children_use_the_parent_cluster(
        self, kind: str, native: bool, child_opt_in: bool
    ) -> None:
        self.experiment.start_date = datetime(2024, 1, 1, tzinfo=UTC)
        self.experiment.end_date = datetime(2024, 1, 8, tzinfo=UTC)
        self.experiment.save()
        child_modifiers = HogQLQueryModifiers(
            optimizeJoinedFilters=True, useNewEventsCluster=True if child_opt_in else None
        )
        parent_modifiers = (
            None
            if native and child_opt_in
            else HogQLQueryModifiers(useNewEventsCluster=native, useNewEventsSchema=native)
        )
        query: ExperimentTrendsQuery | ExperimentFunnelsQuery
        if kind == "trends":
            query = ExperimentTrendsQuery(
                experiment_id=self.experiment.pk,
                count_query=TrendsQuery(series=[EventsNode(event="$pageview")], modifiers=child_modifiers),
                exposure_query=TrendsQuery(
                    series=[EventsNode(event="$feature_flag_called")],
                    modifiers=HogQLQueryModifiers(optimizeJoinedFilters=True),
                ),
                modifiers=parent_modifiers,
            )
        else:
            query = ExperimentFunnelsQuery(
                experiment_id=self.experiment.pk,
                funnels_query=FunnelsQuery(
                    series=[EventsNode(event="$pageview"), EventsNode(event="signup")], modifiers=child_modifiers
                ),
                modifiers=parent_modifiers,
            )
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"),
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]),
        ):
            children: list[QueryRunner]
            runner: QueryRunner
            if isinstance(query, ExperimentTrendsQuery):
                runner = ExperimentTrendsQueryRunner(query=query, team=self.team)
                children = [runner.count_query_runner, runner.exposure_query_runner]
            else:
                runner = ExperimentFunnelsQueryRunner(query=query, team=self.team)
                children = [runner.funnels_query_runner]
            with override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "replacement.example.com"):
                replacement_key = runner.get_cache_key()
            self.assertEqual(runner.get_cache_key() != replacement_key, native)
            if native:
                with patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue:
                    with self.assertRaisesRegex(ExposedHogQLError, "force_blocking"):
                        runner.run(ExecutionMode.CALCULATE_ASYNC_ALWAYS)
                    enqueue.assert_not_called()
            for child in children:
                assert child.modifiers.optimizeJoinedFilters is True
                assert bool(child.modifiers.useNewEventsCluster) is native
                assert child.modifiers.useNewEventsSchema is native
        assert child_modifiers.useNewEventsCluster is (True if child_opt_in else None)
        assert child_modifiers.useNewEventsSchema is None


class TestExperimentThreadRouting(SimpleTestCase):
    @override_settings(IN_UNIT_TESTING=False)
    def test_experiment_threads_preserve_the_parent_host_snapshot(self) -> None:
        host = ["native.example.com"]
        observed = []

        def calculate():
            observed.append(get_new_events_cluster_host())
            raise RuntimeError("query stopped after resolving its host")

        runner = MagicMock()
        runner.experiment.id = 1
        runner.experiment.name = "example"
        runner.feature_flag_key = "example"
        runner.count_query_runner.calculate.side_effect = calculate
        runner.exposure_query_runner.calculate.side_effect = calculate
        with (
            patch("posthog.models.event.new_events_schema.get_instance_setting", side_effect=lambda key: host[0]),
            new_events_cluster_host_scope(),
        ):
            self.assertEqual(get_new_events_cluster_host(), "native.example.com")
            host[0] = "replacement.example.com"
            with self.assertRaisesRegex(RuntimeError, "query stopped"):
                ExperimentTrendsQueryRunner._calculate(runner)
        self.assertEqual(observed, ["native.example.com", "native.example.com"])
