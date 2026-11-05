import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, TeamEventsRetentionConfig
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.testing import create_access_control
from products.product_analytics.backend.facade.events_retention import (
    set_organization_events_retention,
    set_project_events_retention,
)


@override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
class TestEventsRetentionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._set_plan_years(2)
        self.team.event_retention_months = 24
        self.team.save()

    def url(self) -> str:
        return f"/api/projects/{self.team.id}/events_retention/"

    def organization_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/events_retention_setting/"

    def _set_plan_years(self, years: int) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[
                {"key": "product_analytics_data_retention", "limit": years, "unit": "years"},
                {"key": "access_control", "name": "Access control"},
            ]
        )

    def _set_membership(self, level: str) -> None:
        if level == "organization_admin":
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
        else:
            create_access_control(
                team_id=self.team.id,
                resource="project",
                resource_id=str(self.team.id),
                access_level="admin",
                organization_member_id=self.organization_membership.id,
            )

    @parameterized.expand(
        [
            ("utc", "UTC", "2025-09-22"),
            ("ahead_of_utc", "Pacific/Auckland", "2025-09-23"),
        ]
    )
    @time_machine.travel("2026-09-22T23:30:00Z", tick=False)
    def test_reports_the_window_in_the_project_timezone(self, _name: str, tz: str, retained_from: str) -> None:
        self._set_plan_years(1)
        self.team.timezone = tz
        self.team.event_retention_months = 12
        self.team.save()

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "retention_months": 12,
            "retained_from": retained_from,
            "docs_url": "https://posthog.com/docs/data/events-retention",
            "project_retention_months": None,
            "organization_retention_months": None,
            "plan_retention_months": 12,
            "min_retention_months": 1,
            "max_retention_months": 12,
        }

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_reports_no_window_until_retention_is_enforced(self) -> None:
        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] is None
        assert response.json()["retained_from"] is None

    def test_organization_admin_sets_and_clears_the_project_window(self) -> None:
        self._set_membership("organization_admin")
        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=12
        )

        response = self.client.post(self.url(), {"retention_months": 6}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 6
        assert response.json()["project_retention_months"] == 6
        assert ActivityLog.objects.filter(team_id=self.team.id, scope="Team", activity="updated").exists()

        response = self.client.post(self.url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 12
        assert response.json()["project_retention_months"] is None
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("longer_than_the_plan", "organization_admin", 36, status.HTTP_400_BAD_REQUEST),
            ("shorter_than_the_staff_minimum", "organization_admin", 3, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 6, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_a_project_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, min_events_retention_months=6)

        with patch("posthoganalytics.capture") as capture, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()
        assert not any(call.kwargs.get("event") == "events retention set" for call in capture.call_args_list)

    def test_organization_admin_sets_and_clears_the_default_window(self) -> None:
        self._set_membership("organization_admin")

        response = self.client.post(self.organization_url(), {"retention_months": 12}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "organization_retention_months": 12,
            "plan_retention_months": 24,
            "min_retention_months": 1,
            "max_retention_months": 24,
        }
        assert self.client.get(self.url()).json()["retention_months"] == 12
        assert ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()

        response = self.client.post(self.organization_url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert self.client.get(self.url()).json()["retention_months"] == 24
        assert not OrganizationEventsRetentionConfig.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            ("longer_than_the_staff_maximum", "organization_admin", 18, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 6, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_an_organization_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, max_events_retention_months=12)

        with patch("posthoganalytics.capture") as capture, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.organization_url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert not any(call.kwargs.get("event") == "events retention set" for call in capture.call_args_list)
        assert (
            OrganizationEventsRetentionConfig.objects.get(
                organization=self.organization
            ).default_events_retention_months
            is None
        )

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_accepts_windows_before_retention_is_enforced(self) -> None:
        self._set_membership("organization_admin")

        for url in (self.url(), self.organization_url()):
            response = self.client.post(url, {"retention_months": 12}, format="json")

            assert response.status_code == status.HTTP_200_OK
        assert (
            OrganizationEventsRetentionConfig.objects.get(
                organization=self.organization
            ).default_events_retention_months
            == 12
        )
        assert TeamEventsRetentionConfig.objects.get(team=self.team).events_retention_months == 12

    @parameterized.expand([("patch",), ("put",), ("delete",)])
    def test_rejects_other_writes(self, method: str) -> None:
        self._set_membership("organization_admin")

        for url in (self.url(), self.organization_url()):
            response = getattr(self.client, method)(url, {"retention_months": 1})

            assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @parameterized.expand(
        [(scope, source) for scope in ("project", "organization") for source in ("web", "api", "mcp")]
    )
    def test_tracks_saved_retention_changes(self, scope: str, source: str) -> None:
        self._set_membership("organization_admin")
        url = self.url() if scope == "project" else self.organization_url()
        headers = {}
        if source == "api":
            self.client.logout()
            self.client.force_authenticate(user=self.user)
        elif source == "mcp":
            headers = {
                "HTTP_X_POSTHOG_CLIENT": "mcp",
                "HTTP_X_POSTHOG_MCP_SESSION_ID": "test-mcp-session",
                "HTTP_X_POSTHOG_MCP_CONVERSATION_ID": "test-mcp-conversation",
                "HTTP_X_POSTHOG_TRACE_ID": "test-ai-trace",
            }

        self.client.credentials(**headers)
        with patch("posthoganalytics.capture") as capture:
            for before, after in [(None, 6), (6, 12), (12, None)]:
                capture.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(url, {"retention_months": after}, format="json")
                assert response.status_code == status.HTTP_200_OK
                events = [
                    call.kwargs for call in capture.call_args_list if call.kwargs.get("event") == "events retention set"
                ]
                assert len(events) == 1
                event = events[0]
                assert event["distinct_id"] == self.user.distinct_id
                assert event["groups"]["organization"] == str(self.organization.id)
                assert event["properties"]["source"] == source
                assert event["properties"]["scope"] == scope
                assert event["properties"]["retention_months"] == after
                assert event["properties"]["previous_retention_months"] == before
                assert event["properties"]["organization_id"] == str(self.organization.id)
                if scope == "project":
                    assert event["properties"]["project_id"] == self.team.id
                if source == "mcp":
                    assert event["properties"]["$mcp_session_id"] == "test-mcp-session"
                    assert event["properties"]["$mcp_conversation_id"] == "test-mcp-conversation"
                    assert event["properties"]["$ai_trace_id"] == "test-ai-trace"
                else:
                    assert "$mcp_session_id" not in event["properties"]
                    assert "$ai_trace_id" not in event["properties"]

                capture.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(url, {"retention_months": after}, format="json")
                assert response.status_code == status.HTTP_200_OK
                assert not any(call.kwargs.get("event") == "events retention set" for call in capture.call_args_list)

    @parameterized.expand([("project",), ("organization",)])
    def test_saves_retention_with_malformed_analytics_headers(self, scope: str) -> None:
        self._set_membership("organization_admin")
        url = self.url() if scope == "project" else self.organization_url()

        with patch("posthoganalytics.capture"), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"retention_months": 6}, format="json", HTTP_REFERER="https://[")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[f"{scope}_retention_months"] == 6

    @parameterized.expand([("project",), ("organization",)])
    def test_does_not_track_rolled_back_retention_changes(self, scope: str) -> None:
        self._set_membership("organization_admin")
        url = self.url() if scope == "project" else self.organization_url()

        with patch("posthoganalytics.capture") as capture, self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                response = self.client.post(url, {"retention_months": 6}, format="json")
                assert response.status_code == status.HTTP_200_OK
                assert not any(call.kwargs.get("event") == "events retention set" for call in capture.call_args_list)
                transaction.set_rollback(True)

        assert not any(call.kwargs.get("event") == "events retention set" for call in capture.call_args_list)

    @parameterized.expand(
        [(scope, source) for scope in ("project", "organization") for source in ("mcp", "invalid", 42)]
    )
    def test_sanitizes_retention_analytics_properties(self, scope: str, source: str | int) -> None:
        properties: dict[str, object] = {
            "source": source,
            "$mcp_session_id": " \x00session\n ",
            "$mcp_conversation_id": {"id": "invalid"},
            "$ai_trace_id": "t" * 2000,
            "$session_id": 42,
            "mcp_client_name": " \rclient\x7f ",
            "was_impersonated": True,
            "scope": "invalid",
            "organization_id": "invalid",
            "project_id": -1,
            "retention_months": 1200,
            "previous_retention_months": 1200,
            "$set": {"email": "invalid@example.com"},
            "unexpected_property": "invalid",
        }

        with patch("posthoganalytics.capture") as capture, self.captureOnCommitCallbacks(execute=True):
            if scope == "project":
                set_project_events_retention(
                    self.team, 6, user=self.user, was_impersonated=False, analytics_properties=properties
                )
            else:
                set_organization_events_retention(
                    self.organization, 6, user=self.user, was_impersonated=False, analytics_properties=properties
                )
            properties["$ai_trace_id"] = "changed after save"

        events = [call.kwargs for call in capture.call_args_list if call.kwargs.get("event") == "events retention set"]
        assert len(events) == 1
        captured = events[0]["properties"]
        assert captured["source"] == ("mcp" if source == "mcp" else "unknown")
        assert captured["$mcp_session_id"] == "session"
        assert captured["$ai_trace_id"] == "t" * 1000
        assert captured["mcp_client_name"] == "client"
        assert captured["scope"] == scope
        assert captured["organization_id"] == str(self.organization.id)
        assert captured["retention_months"] == 6
        assert captured["previous_retention_months"] is None
        assert captured["was_impersonated"] is False
        assert "$mcp_conversation_id" not in captured
        assert "$session_id" not in captured
        assert "$set" not in captured
        assert "unexpected_property" not in captured
        if scope == "project":
            assert captured["project_id"] == self.team.id
        else:
            assert "project_id" not in captured
