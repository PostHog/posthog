from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError
from rest_framework import status

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition
from products.tracing.backend.alerts.source_config import TracesPlatformAlertConfig
from products.tracing.backend.alerts.wording import describe_transition

_P95_ABOVE = {
    "measure": "latency",
    "percentile": 95,
    "threshold": 500,
    "threshold_operator": "above",
    "window_minutes": 5,
}


class TestTracesAlertConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("latency_without_percentile", {**_P95_ABOVE, "percentile": None}),
            ("percentile_on_a_count", {**_P95_ABOVE, "measure": "request_count"}),
            ("unlisted_percentile", {**_P95_ABOVE, "percentile": 75}),
            ("error_rate_above_one", {**_P95_ABOVE, "measure": "error_rate", "percentile": None, "threshold": 5}),
            ("negative_threshold", {**_P95_ABOVE, "threshold": -1}),
            ("nan_threshold", {**_P95_ABOVE, "threshold": float("nan")}),
            ("unlisted_window", {**_P95_ABOVE, "window_minutes": 7}),
        ]
    )
    def test_a_condition_that_cannot_be_evaluated_is_refused(self, _name: str, condition: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            TracesPlatformAlertConfig.model_validate({"condition": condition})


class TestTracesAlertCreate(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _create(self, source_config: dict[str, Any], grouping: dict[str, Any] | None = None) -> Any:
        body: dict[str, Any] = {
            "source_kind": "traces",
            "name": "Checkout p95",
            "enabled": True,
            "source_config": source_config,
        }
        if grouping is not None:
            body["grouping"] = grouping
        return self.client.post(f"/api/projects/{self.team.id}/platform_alerts/", body, format="json")

    def test_a_traces_alert_is_created_through_the_platform_api(self) -> None:
        response = self._create({"filters": {"serviceNames": ["checkout"]}, "condition": _P95_ABOVE})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["source_kind"] == "traces"
        assert response.json()["check_interval_minutes"] == 1

    @parameterized.expand(
        [
            ("unknown_key", {"serviceNames": ["checkout"]}, _P95_ABOVE, ["status_code"]),
            ("below", {"serviceNames": ["checkout"]}, {**_P95_ABOVE, "threshold_operator": "below"}, ["service_name"]),
            ("operation_without_a_service", None, _P95_ABOVE, ["name"]),
        ]
    )
    def test_a_grouping_the_check_cannot_evaluate_is_refused(
        self, _name: str, filters: dict[str, Any] | None, condition: dict[str, Any], keys: list[str]
    ) -> None:
        source_config: dict[str, Any] = {"condition": condition}
        if filters is not None:
            source_config["filters"] = filters
        response = self._create(source_config, grouping={"mode": "by_result_labels", "keys": keys})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "grouping"

    def test_a_project_without_the_traces_rollout_flag_cannot_create_one(self) -> None:
        self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *_args, **_kwargs: key != "platform-alerts-source-traces",
            )
        )

        response = self._create({"condition": _P95_ABOVE})

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "feature_flag_required"


class TestTracesAlertWording(SimpleTestCase):
    @parameterized.expand(
        [
            ("latency", _P95_ABOVE, 612.5, "p95 latency", "612.5 ms", "above 500 ms"),
            (
                "error_rate",
                {**_P95_ABOVE, "measure": "error_rate", "percentile": None, "threshold": 0.05},
                0.125,
                "Error rate",
                "12.5%",
                "above 5%",
            ),
            (
                "request_count",
                {**_P95_ABOVE, "measure": "request_count", "percentile": None},
                42.0,
                "Requests",
                "42",
                "above 500",
            ),
        ]
    )
    def test_a_message_states_the_value_in_its_measures_unit(
        self, _name: str, condition: dict[str, Any], value: float, measure: str, shown: str, threshold: str
    ) -> None:
        transition = AnnouncedTransition(
            grouping_key="g",
            kind=AlertEventKind.FIRING,
            episode_started_at=datetime(2026, 11, 5, tzinfo=UTC),
            value=value,
            labels={"service_name": "checkout"},
            condition=condition,
            source_config={"condition": condition},
            error_message=None,
            occurred_at=datetime(2026, 11, 5, tzinfo=UTC),
        )

        description = describe_transition(project_id=1, transition=transition)

        assert {detail.label: detail.value for detail in description.details} == {
            "Measure": measure,
            "Value": shown,
            "Threshold": threshold,
            "Window": "5 minutes",
        }
        assert description.context == ("Service: checkout",)
