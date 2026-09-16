from posthog.test.base import APIBaseTest

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType, ExperimentQuery

from posthog.hogql_queries.query_runner import QueryRunner

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentResultCacheVersion(APIBaseTest):
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
        self.runner = ExperimentQueryRunner(
            query=ExperimentQuery(
                experiment_id=experiment.id,
                kind="ExperimentQuery",
                metric=ExperimentMeanMetric(source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL)),
            ),
            team=self.team,
        )

    def test_cache_payload_is_experiment_scoped_and_distinct_from_base(self):
        payload = self.runner.get_cache_payload()
        assert payload["experiment_response_version"] == 3
        assert "experiment_response_version" not in QueryRunner.get_cache_payload(self.runner)
