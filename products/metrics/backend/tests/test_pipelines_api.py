import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries
from products.metrics.backend.models import MetricsPipeline

SIMPLE_CONFIG = {
    "nodes": [
        {
            "id": "capture",
            "name": "Capture",
            "kind": "capture-rs",
            "stats": [
                {
                    "id": "accept",
                    "label": "accept",
                    "format": "rate",
                    "metric_name": "envoy_cluster_upstream_rq",
                    "aggregation": "rate",
                    "thresholds": {"crit": {"upper": 50000}},
                }
            ],
            "headline_stat_ids": ["accept"],
        },
        {
            "id": "kafka",
            "name": "Kafka",
            "kind": "broker",
            "stats": [
                {
                    "id": "lag",
                    "label": "consumer lag",
                    "format": "count",
                    "metric_name": "kminion_kafka_consumer_group_topic_partition_lag",
                    "aggregation": "sum",
                }
            ],
        },
    ],
    "edges": [
        {"source": "capture", "target": "kafka", "metric_name": "envoy_cluster_upstream_rq", "aggregation": "rate"}
    ],
    "variables": [],
}


def fake_run_metric_query(*, team, request):
    points = tuple(
        MetricPoint(time=(request.date_from + dt.timedelta(minutes=i)).isoformat(), value=10.0) for i in range(3)
    )
    return [
        MetricSeries(labels={}, points=points, metric_name=clause.metric_name, clause=clause.name)
        for clause in request.clauses
    ]


class TestMetricsPipelinesAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)

    def _create(self, **overrides):
        payload = {"name": "Logs ingestion", "description": "owned by team-apm", "config": SIMPLE_CONFIG, **overrides}
        return self.client.post(f"/api/projects/{self.team.id}/metrics_pipelines/", payload, format="json")

    def test_create_and_retrieve_round_trip(self):
        response = self._create()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        pipeline_id = response.json()["id"]

        retrieved = self.client.get(f"/api/projects/{self.team.id}/metrics_pipelines/{pipeline_id}/").json()
        assert retrieved["name"] == "Logs ingestion"
        assert retrieved["config"]["nodes"][0]["id"] == "capture"
        assert retrieved["config"]["edges"][0]["source"] == "capture"
        assert retrieved["created_by"]["id"] == self.user.id

    @parameterized.expand(
        [
            ("dangling_edge", {"edges": [{"source": "capture", "target": "nope", "metric_name": "m"}]}),
            ("no_nodes", {"nodes": []}),
        ]
    )
    def test_invalid_config_rejected_with_400(self, _name, config_override):
        response = self._create(config={**SIMPLE_CONFIG, **config_override})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "config" in response.json()["attr"]

    def test_update_config_revalidates(self):
        pipeline_id = self._create().json()["id"]
        bad_config = {**SIMPLE_CONFIG, "edges": [{"source": "kafka", "target": "kafka", "metric_name": "m"}]}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/metrics_pipelines/{pipeline_id}/", {"config": bad_config}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_destroy_soft_deletes_and_hides_from_list(self):
        pipeline_id = self._create().json()["id"]
        response = self.client.delete(f"/api/projects/{self.team.id}/metrics_pipelines/{pipeline_id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        listed = self.client.get(f"/api/projects/{self.team.id}/metrics_pipelines/").json()
        assert listed["count"] == 0
        assert MetricsPipeline.objects.unscoped().get(id=pipeline_id).deleted is True

    def test_other_teams_pipeline_is_not_reachable(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other team")
        other_pipeline = MetricsPipeline.objects.unscoped().create(team=other_team, name="theirs", config=SIMPLE_CONFIG)
        response = self.client.get(f"/api/projects/{self.team.id}/metrics_pipelines/{other_pipeline.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_evaluate_returns_verdicts(self):
        pipeline_id = self._create().json()["id"]
        with patch("products.metrics.backend.facade.api.run_metric_query", side_effect=fake_run_metric_query):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics_pipelines/{pipeline_id}/evaluate/", {}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        evaluation = response.json()
        assert {n["id"] for n in evaluation["nodes"]} == {"capture", "kafka"}
        assert evaluation["nodes"][0]["state"] == "healthy"
        assert evaluation["nodes"][0]["stats"][0]["value"] == 10.0
        assert evaluation["edges"][0]["multiplier"] == 1.0
        assert evaluation["edges"][0]["hot"] is False
        assert evaluation["alerts"] == []

    def test_evaluate_rejects_unknown_variable(self):
        pipeline_id = self._create().json()["id"]
        with patch("products.metrics.backend.facade.api.run_metric_query", side_effect=fake_run_metric_query):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics_pipelines/{pipeline_id}/evaluate/",
                {"variables": {"nope": "x"}},
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_flag_gates_the_api(self):
        self.flag_patcher.stop()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/metrics_pipelines/")
        self.flag_patcher.start()
        assert response.status_code == status.HTTP_403_FORBIDDEN
