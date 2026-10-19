from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentExposureQuery,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    HogQLQueryModifiers,
    PrecomputationMode,
)

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models.instance_setting import override_instance_config
from posthog.models.team.extensions import get_or_create_team_extension

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
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
