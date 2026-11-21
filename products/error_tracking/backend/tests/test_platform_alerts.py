from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError
from rest_framework import status

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition
from products.error_tracking.backend.platform_alerts.source_config import ErrorTrackingPlatformAlertConfig
from products.error_tracking.backend.platform_alerts.wording import describe_transition

_NEW_ISSUES = {"triggers": ["issue_created"]}
_ISSUE_GROUPING = {"mode": "by_result_labels", "keys": ["issue_id"]}


class TestErrorTrackingAlertConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_trigger", {"triggers": []}),
            ("unknown_trigger", {"triggers": ["issue_spiking"]}),
            ("unknown_key", {"triggers": ["issue_created"], "throttle_seconds": 60}),
        ]
    )
    def test_a_condition_that_cannot_be_evaluated_is_refused(self, _name: str, condition: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            ErrorTrackingPlatformAlertConfig.model_validate({"condition": condition})


class TestErrorTrackingAlertCreate(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _create(self, source_config: dict[str, Any], grouping: dict[str, Any] | None = _ISSUE_GROUPING) -> Any:
        body: dict[str, Any] = {
            "source_kind": "error_tracking",
            "name": "New checkout errors",
            "enabled": True,
            "source_config": source_config,
        }
        if grouping is not None:
            body["grouping"] = grouping
        return self.client.post(f"/api/projects/{self.team.id}/platform_alerts/", body, format="json")

    def test_an_error_tracking_alert_is_created_through_the_platform_api(self) -> None:
        response = self._create(
            {
                "condition": {"triggers": ["issue_created", "issue_reopened"]},
                "filters": {
                    "properties": [
                        {"key": "$exception_types", "value": ["TypeError"], "operator": "exact", "type": "event"}
                    ]
                },
            }
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["source_kind"] == "error_tracking"
        assert response.json()["check_interval_minutes"] == 1

    @parameterized.expand(
        [
            ("single_instance", None),
            ("another_label", {"mode": "by_result_labels", "keys": ["issue_name"]}),
        ]
    )
    def test_an_alert_not_grouped_by_issue_is_refused(self, _name: str, grouping: dict[str, Any] | None) -> None:
        response = self._create({"condition": _NEW_ISSUES}, grouping=grouping)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "grouping"

    @parameterized.expand(
        [
            ("not_an_event_property", {"key": "not_a_function(1)", "type": "hogql"}),
            # It would compile to a constant true, so the alert would match every issue.
            ("without_a_value", {"key": "environment", "type": "event", "operator": "exact"}),
        ]
    )
    def test_filters_that_cannot_run_are_refused(self, _name: str, property_filter: dict[str, Any]) -> None:
        response = self._create({"condition": _NEW_ISSUES, "filters": {"properties": [property_filter]}})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "source_config"

    def test_an_incident_destination_is_refused(self) -> None:
        # The alert never resolves, so an incident manager would be saved and never hear anything.
        created = self._create({"condition": _NEW_ISSUES})
        assert created.status_code == status.HTTP_201_CREATED, created.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/platform_alerts/{created.json()['id']}/destinations/",
            {"type": "pagerduty", "pagerduty_routing_key": "0123456789abcdef0123456789abcdef"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "type"

    def test_a_project_without_the_rollout_flag_cannot_create_one(self) -> None:
        self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *_args, **_kwargs: key != "platform-alerts-source-error-tracking",
            )
        )

        response = self._create({"condition": _NEW_ISSUES})

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "feature_flag_required"


class TestErrorTrackingAlertWording(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "by_fingerprint",
                {"fingerprint": "abc/def"},
                "http://localhost:8010/project/1/error-tracking/fingerprint/abc%2Fdef",
            ),
            ("by_issue_without_fingerprint", {}, "http://localhost:8010/project/1/error-tracking/issue-1"),
        ]
    )
    def test_a_message_names_the_issue_and_links_to_it(
        self, _name: str, source_detail: dict[str, Any], expected_url: str
    ) -> None:
        transition = AnnouncedTransition(
            grouping_key="issue-1",
            kind=AlertEventKind.FIRING,
            episode_started_at=datetime(2026, 11, 17, tzinfo=UTC),
            value=None,
            labels={"issue_id": "issue-1", "issue_name": "TypeError: x is undefined", "trigger": "issue_reopened"},
            condition={"triggers": ["issue_reopened"]},
            source_config={"condition": {"triggers": ["issue_reopened"]}},
            error_message=None,
            occurred_at=datetime(2026, 11, 17, tzinfo=UTC),
            source_detail=source_detail,
        )

        description = describe_transition(project_id=1, transition=transition)

        assert {detail.label: detail.value for detail in description.details} == {
            "Issue": "TypeError: x is undefined",
            "Change": "Reopened",
        }
        assert description.data_link is not None
        assert description.data_link.url == expected_url
