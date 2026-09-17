import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables


class TestMetricAttributesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True
    now: dt.datetime

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        truncate_metrics_tables()

        cls.now = timezone.now().replace(second=0, microsecond=0)
        recent = [(cls.now - dt.timedelta(minutes=m), 1.0) for m in (2, 3, 4)]
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="checkout",
            points=recent,
            labels={"env": "prod", "region": "us"},
            resource_labels={"k8s.pod.name": "pod-1", "region": "us", "service.name": "checkout"},
        )
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="billing",
            points=[(cls.now - dt.timedelta(minutes=5), 1.0)],
            labels={"env": "dev", "service_name": "billing"},
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
        assert body["results"] == [
            {"name": "service_name", "attribute_count": 4},
            {"name": "region", "attribute_count": 6},
            {"name": "env", "attribute_count": 4},
            {"name": "k8s.pod.name", "attribute_count": 3},
            {"name": "stale_key", "attribute_count": 1},
        ]
        assert body["count"] == 5

    @parameterized.expand(
        [
            ("substring_of_attribute_key", "env", ["env"]),
            ("substring_of_synthetic_service_name", "serv", ["service_name"]),
            ("dotted_service_name", "service.name", ["service_name"]),
            ("attribute_count_order", "e", ["service_name", "region", "env", "k8s.pod.name", "stale_key"]),
        ]
    )
    def test_attributes_search_filters_keys(self, _name: str, search: str, expected: list[str]) -> None:
        response = self._get("attributes", {"search": search})
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == expected

    @parameterized.expand([("utc", 0), ("half_hour_offset", 330)])
    def test_attributes_use_hourly_window(self, _name: str, offset_minutes: int):
        tz = dt.timezone(dt.timedelta(minutes=offset_minutes))
        response = self._get(
            "attributes",
            {
                "dateFrom": (self.now - dt.timedelta(hours=1)).astimezone(tz).isoformat(),
                "dateTo": self.now.isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [
            {"name": "service_name", "attribute_count": 4},
            {"name": "region", "attribute_count": 6},
            {"name": "env", "attribute_count": 4},
            {"name": "k8s.pod.name", "attribute_count": 3},
        ]

    def test_attributes_exclude_buckets_after_the_window(self):
        response = self._get(
            "attributes",
            {
                "dateFrom": (self.now - dt.timedelta(hours=4)).isoformat(),
                "dateTo": (self.now - dt.timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [
            {"name": "service_name", "attribute_count": None},
            {"name": "stale_key", "attribute_count": 1},
        ]

    @parameterized.expand(
        [
            ("limit", {"limit": 1}, 4),
            ("no_metadata", {"metricName": "unknown"}, None),
            ("no_alias_rows", {"metricName": "queue_depth", "search": "serv"}, None),
        ]
    )
    def test_service_key_sums_alias_rows(self, _name: str, params: dict, expected_count: int | None):
        response = self._get("attributes", params)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [{"name": "service_name", "attribute_count": expected_count}]

    def test_attributes_metric_name_limits_keys_to_that_metric(self):
        response = self._get("attributes", {"metricName": "http_requests"})
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == [
            {"name": "service_name", "attribute_count": 4},
            {"name": "region", "attribute_count": 6},
            {"name": "env", "attribute_count": 4},
            {"name": "k8s.pod.name", "attribute_count": 3},
        ]

    @parameterized.expand([("all_metrics", "", ["prod", "dev"]), ("other_metric", "queue_depth", [])])
    def test_attribute_values_returns_values_with_aggregated_counts(
        self, _name: str, metric_name: str, expected: list[str]
    ):
        response = self._get("attribute_values", {"key": "env", "metricName": metric_name})
        assert response.status_code == status.HTTP_200_OK
        values = [
            {"id": "prod", "name": "prod", "count": 3},
            {"id": "dev", "name": "dev", "count": 1},
        ]
        assert response.json()["results"] == [value for value in values if value["name"] in expected]

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
        scoped_response = self._get("attribute_values", {"key": key, "metricName": "queue_depth"})
        assert scoped_response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in scoped_response.json()["results"]] == ["checkout"]

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
