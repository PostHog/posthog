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

    @parameterized.expand([("recent", 0), ("historical", 10)])
    def test_attributes_use_recent_metadata_without_enforcing_end_time(self, _name: str, end_minutes_ago: int):
        response = self._get(
            "attributes",
            {
                "dateFrom": (self.now - dt.timedelta(hours=1)).isoformat(),
                "dateTo": (self.now - dt.timedelta(minutes=end_minutes_ago)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [
            {"name": "env", "value_count": 2},
            {"name": "service_name", "value_count": 2},
            {"name": "k8s.pod.name", "value_count": 1},
            {"name": "region", "value_count": 1},
        ]

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

    @parameterized.expand(
        [
            ("matching_metric", "http_requests", "region", ["us"]),
            ("other_metric", "queue_depth", "region", []),
            ("service_name_matching_metric", "http_requests", "service_name", ["checkout", "billing"]),
            ("service_name_unknown_metric", "missing_metric", "service_name", []),
        ]
    )
    def test_attribute_values_metric_name_limits_values_to_that_metric(
        self, _name: str, metric_name: str, key: str, expected: list[str]
    ) -> None:
        response = self._get(
            "attribute_values",
            {"key": key, "metricName": metric_name, "dateFrom": (self.now - dt.timedelta(hours=6)).isoformat()},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [r["name"] for r in response.json()["results"]] == expected

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

    @parameterized.expand(
        [
            ("no_search", "job.duration", "", ["service.name", "env"]),
            ("underscore_search", "job.duration", "service_name", ["service.name"]),
            ("dotted_search", "job.duration", "service.name", ["service.name"]),
            ("project_wide_no_search", "", "", ["service.name", "env"]),
            ("project_wide_underscore_search", "", "service_name", ["service.name"]),
            ("project_wide_dotted_search", "", "service.name", ["service.name"]),
        ]
    )
    def test_service_name_resource_attribute_is_listed_once(
        self, _name: str, metric_name: str, search: str, expected: list[str]
    ) -> None:
        truncate_metrics_tables()
        now = timezone.now().replace(second=0, microsecond=0)
        for service in ("checkout", "billing"):
            seed_metric(
                team_id=self.team.id,
                metric_name="job.duration",
                service_name=service,
                points=[(now - dt.timedelta(minutes=2), 1.0)],
                labels={"env": "prod"},
                resource_labels={"service.name": service},
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/metrics/attributes/", {"metricName": metric_name, "search": search}
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [r["name"] for r in response.json()["results"]] == expected

    @parameterized.expand(
        [
            ("one_metric", "job.duration", "service_name"),
            ("project_wide", "", "service_name"),
            ("project_wide_dotted_datapoint_label", "", "service.name"),
        ]
    )
    def test_services_without_dotted_resource_attribute_keep_one_synthetic_key(
        self, _name: str, metric_name: str, datapoint_service_key: str
    ) -> None:
        truncate_metrics_tables()
        now = timezone.now().replace(second=0, microsecond=0)
        seed_metric(
            team_id=self.team.id,
            metric_name="job.duration",
            service_name="checkout",
            points=[(now - dt.timedelta(minutes=2), 1.0)],
            labels={"env": "prod"},
            resource_labels={"service.name": "checkout"},
        )
        seed_metric(
            team_id=self.team.id,
            metric_name="job.duration",
            service_name="billing",
            points=[(now - dt.timedelta(minutes=2), 1.0)],
            labels={"env": "prod", datapoint_service_key: "billing"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/metrics/attributes/", {"metricName": metric_name})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == [
            {"name": "env", "value_count": 1},
            {"name": "service.name", "value_count": 1},
            {"name": "service_name", "value_count": 1},
        ]


class TestMetricAttributeValueSearchAPI(ClickhouseTestMixin, APIBaseTest):
    """`search_values` lets a remembered value, such as a service or an environment,
    find the attribute key that carries it, the way logs and traces already do."""

    CLASS_DATA_LEVEL_SETUP = True
    now: dt.datetime

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        truncate_metrics_tables()

        cls.now = timezone.now().replace(second=0, microsecond=0)
        recent = [(cls.now - dt.timedelta(minutes=m), 1.0) for m in (2, 3)]
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="checkout",
            points=recent,
            labels={"env": "prod", "region": "us-east", "zone": "region-west"},
            resource_labels={"k8s.pod.name": "pod-1"},
        )
        seed_metric(
            team_id=cls.team.id,
            metric_name="http_requests",
            service_name="billing",
            points=[(cls.now - dt.timedelta(minutes=4), 1.0)],
            labels={"env": "dev"},
        )
        seed_metric(
            team_id=cls.team.id,
            metric_name="queue_depth",
            service_name="checkout",
            points=[(cls.now - dt.timedelta(minutes=5), 1.0)],
            labels={"stale_key": "old"},
        )

    def _results(self, params: dict) -> list[dict]:
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/attributes/", params)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["results"]

    def test_value_search_is_off_by_default(self):
        # No attribute key contains "checkout", so only a value search can find the service key.
        assert self._results({"search": "checkout"}) == []

    def test_value_search_finds_the_key_that_carries_the_value(self):
        assert self._results({"search": "checkout", "search_values": "true"}) == [
            {"name": "service_name", "value_count": 1, "matchedOn": "value", "matchedValue": "checkout"}
        ]

    def test_value_search_reports_one_sample_value_per_key(self):
        assert self._results({"metricName": "http_requests", "search": "prod", "search_values": "true"}) == [
            {"name": "env", "value_count": 1, "matchedOn": "value", "matchedValue": "prod"}
        ]

    def test_key_matches_come_before_value_matches(self):
        results = self._results({"metricName": "http_requests", "search": "region", "search_values": "true"})

        # "region" names a key and also appears inside the value of another key.
        assert results == [
            {"name": "region", "value_count": 1},
            {"name": "zone", "value_count": 1, "matchedOn": "value", "matchedValue": "region-west"},
        ]

    def test_short_search_does_not_probe_values(self):
        # Under the minimum length only the key-name path runs, so "zone" is not suggested.
        assert self._results({"metricName": "http_requests", "search": "reg", "search_values": "true"}) == [
            {"name": "region", "value_count": 1}
        ]

    def test_the_service_key_name_still_matches_in_value_mode(self):
        assert self._results({"metricName": "http_requests", "search": "service", "search_values": "true"}) == [
            {"name": "service_name", "value_count": 2}
        ]

    @parameterized.expand(
        [
            ("value_on_the_metric", "http_requests", "prod", ["env"]),
            ("value_on_another_metric", "queue_depth", "prod", []),
            ("service_of_the_metric", "queue_depth", "checkout", ["service_name"]),
        ]
    )
    def test_value_search_stays_inside_the_metric(
        self, _name: str, metric_name: str, search: str, expected: list[str]
    ) -> None:
        results = self._results({"metricName": metric_name, "search": search, "search_values": "true"})
        assert [r["name"] for r in results] == expected

    def test_value_search_with_no_match_returns_nothing(self):
        assert self._results({"search": "nothing_here", "search_values": "true"}) == []
