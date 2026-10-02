import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.query import execute_hogql_query

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
            resource_labels={"k8s.pod.name": "pod-1", "region": "us"},
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
        assert body["results"] == [
            {"name": "env", "value_count": 2},
            {"name": "service_name", "value_count": 2},
            {"name": "k8s.pod.name", "value_count": 1},
            {"name": "region", "value_count": 1},
            {"name": "stale_key", "value_count": 1},
        ]
        assert body["count"] == 5

    @parameterized.expand(
        [
            ("substring_of_attribute_key", "env", ["env"]),
            ("substring_of_synthetic_service_name", "serv", ["service_name"]),
            ("dotted_service_name", "service.name", ["service_name"]),
            ("value_count_order", "e", ["env", "service_name", "k8s.pod.name", "region", "stale_key"]),
        ]
    )
    def test_attributes_search_filters_keys(self, _name: str, search: str, expected: list[str]) -> None:
        response = self._get("attributes", {"search": search})
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == expected

    @parameterized.expand(
        [
            (
                "all_metrics_recent_hour",
                1,
                0,
                "",
                [
                    {"name": "env", "value_count": 2},
                    {"name": "service_name", "value_count": 2},
                    {"name": "k8s.pod.name", "value_count": 1},
                    {"name": "region", "value_count": 1},
                ],
            ),
            (
                "all_metrics_older_window",
                4,
                2,
                "",
                [{"name": "service_name", "value_count": 1}, {"name": "stale_key", "value_count": 1}],
            ),
            (
                "one_metric_older_window",
                4,
                2,
                "queue_depth",
                [{"name": "service_name", "value_count": 1}, {"name": "stale_key", "value_count": 1}],
            ),
            ("one_metric_outside_window", 4, 2, "http_requests", [{"name": "service_name", "value_count": 0}]),
        ]
    )
    def test_attributes_come_from_the_selected_window(
        self, _name: str, start_hours_ago: int, end_hours_ago: int, metric_name: str, expected: list[dict]
    ) -> None:
        response = self._get(
            "attributes",
            {
                "metricName": metric_name,
                "dateFrom": (self.now - dt.timedelta(hours=start_hours_ago)).isoformat(),
                "dateTo": (self.now - dt.timedelta(hours=end_hours_ago)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == expected

    def test_attributes_metric_name_limits_keys_to_that_metric(self):
        response = self._get("attributes", {"metricName": "http_requests"})
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == [
            {"name": "env", "value_count": 2},
            {"name": "service_name", "value_count": 2},
            {"name": "k8s.pod.name", "value_count": 1},
            {"name": "region", "value_count": 1},
        ]

    def test_attributes_without_recent_series_return_zero_service_values(self):
        response = self._get("attributes", {"metricName": "missing_metric"})
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == [{"name": "service_name", "value_count": 0}]

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


class TestMetricAttributeDistinctValuesAPI(ClickhouseTestMixin, APIBaseTest):
    def test_attributes_count_distinct_values_with_grouping_scope_precedence(self):
        truncate_metrics_tables()
        now = timezone.now().replace(second=0, microsecond=0)
        for index, (labels, resource_labels) in enumerate(
            [
                ({"env": "prod", "region": "ignored-a"}, {"region": "us"}),
                ({"env": "prod", "region": "ignored-b"}, {"region": "us"}),
                ({"env": "prod", "region": "eu"}, {"region": ""}),
                ({"env": "prod", "region": ""}, {}),
            ]
        ):
            seed_metric(
                team_id=self.team.id,
                metric_name="distinct_values",
                service_name="checkout",
                points=[(now - dt.timedelta(minutes=2), 1.0)],
                labels={**labels, "instance": str(index)},
                resource_labels=resource_labels,
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/metrics/attributes/", {"metricName": "distinct_values"}
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == [
            {"name": "instance", "value_count": 4},
            {"name": "region", "value_count": 3},
            {"name": "env", "value_count": 1},
            {"name": "service_name", "value_count": 1},
        ]


class TestMetricAttributeSlicesAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        truncate_metrics_tables()

        now = timezone.now().replace(second=0, microsecond=0)
        seed_metric(
            team_id=cls.team.id,
            metric_name="requests",
            service_name="checkout",
            points=[(now - dt.timedelta(minutes=10), 1.0)],
            labels={"new_key": "a", "shared": "recent"},
        )
        # Older than the recent two-hour slice of the default 24 hour window.
        for index in range(3):
            seed_metric(
                team_id=cls.team.id,
                metric_name="requests",
                service_name="checkout",
                points=[(now - dt.timedelta(hours=5), 1.0)],
                labels={"old_key": f"v{index}", "shared": f"old{index}"},
            )

    def _get(self, action: str, params: dict) -> tuple[list[dict], int]:
        with patch(
            "products.metrics.backend.metric_attributes_query_runner.execute_hogql_query",
            wraps=execute_hogql_query,
        ) as execute:
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/{action}", params)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["results"], execute.call_count

    @parameterized.expand(
        [
            ("all_metrics_recent_slice_fills_limit", "", 3, ["new_key", "service_name", "shared"], 1),
            ("all_metrics_older_slice_fills_rest", "", 4, ["new_key", "service_name", "shared", "old_key"], 2),
            ("one_metric_recent_slice_fills_limit", "requests", 3, ["new_key", "service_name", "shared"], 1),
            ("one_metric_older_slice_fills_rest", "requests", 4, ["new_key", "service_name", "shared", "old_key"], 2),
        ]
    )
    def test_attributes_read_the_older_slice_only_to_fill_the_limit(
        self, _name: str, metric_name: str, limit: int, expected: list[str], expected_queries: int
    ) -> None:
        results, queries = self._get("attributes", {"metricName": metric_name, "limit": limit})
        assert [r["name"] for r in results] == expected
        assert queries == expected_queries

    @parameterized.expand(
        [
            ("recent_slice_fills_limit", 1, ["recent"], 1),
            ("older_slice_fills_rest", 100, ["recent", "old0", "old1", "old2"], 2),
        ]
    )
    def test_attribute_values_read_the_older_slice_only_to_fill_the_limit(
        self, _name: str, limit: int, expected: list[str], expected_queries: int
    ) -> None:
        results, queries = self._get("attribute_values", {"key": "shared", "limit": limit})
        assert [r["name"] for r in results] == expected
        assert queries == expected_queries
