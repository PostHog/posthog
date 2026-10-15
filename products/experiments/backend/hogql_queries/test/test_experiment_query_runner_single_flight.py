from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType, ExperimentQuery

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentQueryRunnerSingleFlight(APIBaseTest):
    def setUp(self):
        super().setUp()
        feature_flag = FeatureFlag.objects.create(
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
        experiment = Experiment.objects.create(name="test-experiment", team=self.team, feature_flag=feature_flag)
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
