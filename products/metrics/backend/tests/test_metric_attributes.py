import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.tests._seeder import seed_metric


class TestMetricAttributesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True
    now: dt.datetime

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # metric_attributes is fed by MVs on metrics1, so truncating metrics1
        # alone (as sibling test classes do) leaves attribute rows behind.
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        sync_execute("TRUNCATE TABLE IF EXISTS metric_attributes")

        cls.now = timezone.now().replace(second=0, microsecond=0)
        recent = [(cls.now - dt.timedelta(minutes=m), 1.0) for m in (2, 3, 4)]
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="checkout",
            points=recent,
            labels={"env": "prod", "region": "us"},
            resource_labels={"k8s.pod.name": "pod-1"},
        )
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="billing",
            points=[(cls.now - dt.timedelta(minutes=5), 1.0)],
            labels={"env": "dev"},
        )
        # Outside a 1h window but inside the default 7d lookback.
        seed_metric(
            team_id=cls.team.id,
            metric_name="queue_depth",
            service_name="checkout",
            points=[(cls.now - dt.timedelta(hours=3), 1.0)],
            labels={"stale_key": "old"},
        )

    def _get(self, action: str, params: dict | None = None):
        return self.client.get(f"/api/projects/{self.team.id}/metrics/{action}", params or {})

    def test_attributes_merges_datapoint_and_resource_keys(self):
        response = self._get("attributes")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        # service_name is synthesized (it lives in its own column, never as an
        # attribute row); the rest order by total count desc, then name asc.
        assert [r["name"] for r in body["results"]] == [
            "service_name",
            "env",
            "k8s.pod.name",
            "region",
            "stale_key",
        ]
        assert body["count"] == 5

    @parameterized.expand(
        [
            ("substring_of_attribute_key", "env", ["env"]),
            ("substring_of_synthetic_service_name", "serv", ["service_name"]),
        ]
    )
    def test_attributes_search_filters_keys(self, _name: str, search: str, expected: list[str]) -> None:
        response = self._get("attributes", {"search": search})
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == expected

    def test_attributes_window_excludes_out_of_range_buckets(self):
        response = self._get("attributes", {"dateFrom": (self.now - dt.timedelta(hours=1)).isoformat()})
        assert response.status_code == status.HTTP_200_OK
        names = [r["name"] for r in response.json()["results"]]
        assert "stale_key" not in names
        assert "env" in names

    def test_attribute_values_returns_values_with_aggregated_counts(self):
        response = self._get("attribute_values", {"key": "env"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [
            {"id": "prod", "name": "prod", "count": 3},
            {"id": "dev", "name": "dev", "count": 1},
        ]

    def test_attribute_values_search_filters_values(self):
        # The property-values autocomplete sends the typed input as `value`.
        response = self._get("attribute_values", {"key": "env", "value": "pr"})
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == ["prod"]

    @parameterized.expand([("underscore_spelling", "service_name"), ("dotted_spelling", "service.name")])
    def test_attribute_values_for_service_name_read_the_column(self, _name: str, key: str) -> None:
        response = self._get("attribute_values", {"key": key})
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == ["checkout", "billing"]

    @parameterized.expand(
        [
            ("missing_key", "attribute_values", {}),
            ("bad_limit", "attributes", {"limit": "0"}),
            ("non_numeric_limit", "attributes", {"limit": "lots"}),
            ("bad_date", "attributes", {"dateFrom": "not-a-date"}),
        ]
    )
    def test_bad_params_are_400(self, _name: str, action: str, params: dict) -> None:
        response = self._get(action, params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
