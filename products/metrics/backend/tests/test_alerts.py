from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError
from rest_framework import status

from products.metrics.backend.alerts.source_config import MetricsAlertConfig

_QUERY = 'sum(kafka_consumer_group_lag{group="example"})'


class TestMetricsAlertConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("threshold_without_operator", {"query": _QUERY, "condition": {"threshold": 10}}),
            ("threshold_without_value", {"query": _QUERY, "condition": {"operator": ">"}}),
            ("present_with_threshold", {"query": _QUERY, "condition": {"kind": "present", "threshold": 1}}),
            ("empty_query", {"query": "", "condition": {"kind": "present"}}),
            ("unknown_operator", {"query": _QUERY, "condition": {"operator": "above", "threshold": 1}}),
        ]
    )
    def test_a_config_that_cannot_be_evaluated_is_refused(self, _name: str, config: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            MetricsAlertConfig.model_validate(config)


class TestMetricsAlertCreate(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))

    def _create(self, source_config: dict[str, Any]) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/platform_alerts/",
            {"source_kind": "metrics", "name": "Consumer lag", "enabled": True, "source_config": source_config},
            format="json",
        )

    def test_a_metrics_alert_is_created_through_the_platform_api(self) -> None:
        response = self._create({"query": _QUERY, "condition": {"operator": ">", "threshold": 1000}})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["source_kind"] == "metrics"
        assert response.json()["check_interval_minutes"] == 1
