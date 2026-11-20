from datetime import date

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.events_plan_deletion import TeamEventsPlanDeletion
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, TeamEventsRetentionConfig
from posthog.models.organization import OrganizationMembership
from posthog.models.team.event_retention import EVENTS_DATA_RETENTION_FLAG

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

    def _set_plan_years(self, years: int, standard: bool = False) -> None:
        standard_feature = [{"key": "product_analytics_standard_data_retention"}] if standard else []
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[
                {"key": "product_analytics_data_retention", "limit": years, "unit": "years"},
                {"key": "access_control", "name": "Access control"},
                *standard_feature,
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
            "next_deletion_on": None,
            "next_deletion_before": None,
            "scheduled_pass_on": None,
            "first_pass_on": "2027-01-03",
            "default_period_deletes": True,
            "organization_retention_months": None,
            "default_retention_months": 12,
            "default_is_grandfathered": False,
            "plan_retention_months": 12,
            "min_retention_months": 1,
            "max_retention_months": 12,
            "retention_months_choices": [1, 3, 12, 24, 36, 60, 84],
            "next_monthly_cleanup_on": "2026-10-03",
        }

    @parameterized.expand(
        [
            ("pass", 24, 24, None, ("2026-11-03", "2024-11-01", "2026-11-03")),
            ("shorter_period_pushes_the_pass", 24, 12, None, ("2027-01-03", "2026-01-01", "2027-01-03")),
            ("set_period_keeps_its_pass", 12, 24, 12, ("2026-10-03", "2025-10-01", "2026-11-03")),
            ("set_period_without_a_pass", None, 24, 12, ("2026-10-03", "2025-10-01", None)),
            ("not_admitted", None, 84, None, (None, None, None)),
            (
                "due_pass_shortens_a_set_period_past_the_plan",
                12,
                12,
                36,
                ("2026-10-03", "2025-10-01", "2026-10-03"),
                date(2026, 10, 3),
            ),
            ("overdue_pass", 24, 24, None, ("2026-10-03", "2024-10-01", "2026-09-03"), date(2026, 9, 3)),
        ]
    )
    @time_machine.travel("2026-09-22T20:00:00Z", tick=False)
    def test_reports_the_next_deletion(
        self,
        _name: str,
        stored_months: int | None,
        plan_months: int,
        setting_months: int | None,
        expected: tuple[str | None, str | None, str | None],
        pass_on: date = date(2026, 11, 3),
    ) -> None:
        self.team.event_retention_months = plan_months
        self.team.save()
        if setting_months is not None:
            TeamEventsRetentionConfig.objects.create(team=self.team, events_retention_months=setting_months)
        if stored_months is not None:
            TeamEventsPlanDeletion.objects.create(team=self.team, months=stored_months, next_deletion_on=pass_on)

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert (body["next_deletion_on"], body["next_deletion_before"], body["scheduled_pass_on"]) == expected

    @parameterized.expand(
        [
            ("standard_plan_defaults_to_24_months", True, None, 24, False),
            ("grandfathered_plan_defaults_to_its_whole_period", False, None, 84, True),
            ("staff_minimum_raises_the_standard_default", True, 36, 36, False),
        ]
    )
    def test_reports_the_default_period(
        self, _name: str, standard: bool, staff_min: int | None, expected_months: int, grandfathered: bool
    ) -> None:
        self._set_plan_years(7, standard=standard)
        self.team.event_retention_months = 84
        self.team.save()
        if staff_min is not None:
            OrganizationEventsRetentionConfig.objects.create(
                organization=self.organization, min_events_retention_months=staff_min
            )

        project = self.client.get(self.url()).json()
        organization = self.client.get(self.organization_url()).json()

        assert (project["retention_months"], project["default_retention_months"]) == (expected_months, expected_months)
        assert (organization["default_retention_months"], organization["max_retention_months"]) == (expected_months, 84)
        assert organization["default_is_grandfathered"] is grandfathered

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_reports_no_window_until_retention_is_enforced(self) -> None:
        TeamEventsPlanDeletion.objects.create(team=self.team, months=24, next_deletion_on=date(2027, 2, 3))

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] is None
        assert response.json()["retained_from"] is None
        assert response.json()["next_deletion_on"] is None
        assert response.json()["default_period_deletes"] is False

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=None)
    @time_machine.travel("2026-09-22T20:00:00Z", tick=False)
    def test_reports_no_pass_while_deletion_is_off(self) -> None:
        TeamEventsPlanDeletion.objects.create(team=self.team, months=24, next_deletion_on=date(2026, 11, 3))

        with (
            patch("posthog.models.team.event_retention.is_cloud", return_value=True),
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda flag, *args, **kwargs: flag == EVENTS_DATA_RETENTION_FLAG,
            ),
        ):
            response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] is not None
        assert (response.json()["next_deletion_on"], response.json()["default_period_deletes"]) == (None, False)

    @time_machine.travel("2026-09-22T20:00:00Z", tick=False)
    def test_organization_admin_sets_and_clears_the_project_window(self) -> None:
        self._set_membership("organization_admin")
        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=12
        )

        response = self.client.post(self.url(), {"retention_months": 3}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 3
        assert response.json()["project_retention_months"] == 3
        assert response.json()["next_deletion_on"] == "2026-10-03"
        assert ActivityLog.objects.filter(team_id=self.team.id, scope="Team", activity="updated").exists()

        response = self.client.post(self.url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 12
        assert response.json()["project_retention_months"] is None
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()

    @time_machine.travel("2026-09-22T20:00:00Z", tick=False)
    def test_clearing_a_set_period_after_a_plan_upgrade_waits_a_full_interval(self) -> None:
        self._set_membership("organization_admin")
        self._set_plan_years(7, standard=True)
        self.team.event_retention_months = 84
        self.team.save()
        TeamEventsRetentionConfig.objects.create(team=self.team, events_retention_months=36)
        TeamEventsPlanDeletion.objects.create(team=self.team, months=12, next_deletion_on=date(2026, 10, 3))

        response = self.client.post(self.url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert (response.json()["retention_months"], response.json()["scheduled_pass_on"]) == (24, "2027-01-03")

    @parameterized.expand(
        [
            ("longer_than_the_plan", "organization_admin", 36, status.HTTP_400_BAD_REQUEST),
            ("shorter_than_the_staff_minimum", "organization_admin", 3, status.HTTP_400_BAD_REQUEST),
            ("not_one_of_the_choices", "organization_admin", 18, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 12, status.HTTP_403_FORBIDDEN),
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

    @time_machine.travel("2026-09-22T20:00:00Z", tick=False)
    def test_organization_admin_sets_and_clears_the_default_window(self) -> None:
        self._set_membership("organization_admin")

        response = self.client.post(self.organization_url(), {"retention_months": 12}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "organization_retention_months": 12,
            "default_retention_months": 24,
            "default_is_grandfathered": False,
            "plan_retention_months": 24,
            "min_retention_months": 1,
            "max_retention_months": 24,
            "retention_months_choices": [1, 3, 12, 24, 36, 60, 84],
            "next_monthly_cleanup_on": "2026-10-03",
        }
        project = self.client.get(self.url()).json()
        assert (project["retention_months"], project["next_deletion_on"]) == (12, "2026-10-03")
        assert ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()

        response = self.client.post(self.organization_url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert self.client.get(self.url()).json()["retention_months"] == 24
        assert not OrganizationEventsRetentionConfig.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            ("longer_than_the_staff_maximum", "organization_admin", 24, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 12, status.HTTP_403_FORBIDDEN),
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
        assert not TeamEventsPlanDeletion.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("project_admin", "project_admin", "project", "deletion_count", 3, status.HTTP_403_FORBIDDEN),
            ("project_admin", "project_admin", "organization", "deletion_count", 3, status.HTTP_403_FORBIDDEN),
            (
                "project_admin",
                "project_admin",
                "organization",
                "downgrade_deletion_count",
                3,
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "period_before_any_date",
                "organization_admin",
                "project",
                "deletion_count",
                100000,
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "period_before_any_date",
                "organization_admin",
                "organization",
                "deletion_count",
                100000,
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_rejects_a_deletion_count(
        self, _name: str, level: str, scope: str, count: str, months: int, expected_status: int
    ) -> None:
        self._set_membership(level)
        url = self.url() if scope == "project" else self.organization_url()

        response = self.client.get(f"{url}{count}/", {"retention_months": months})

        assert response.status_code == expected_status

    @parameterized.expand(
        [
            (
                "organization_past_its_time_budget",
                "organization",
                "products.product_analytics.backend.events_retention.EVENTS_DELETED_QUERY_SECONDS",
                {"new": 0},
                status.HTTP_504_GATEWAY_TIMEOUT,
            ),
            (
                "project_without_a_free_query_slot",
                "project",
                "products.product_analytics.backend.presentation.query_concurrency.app_org_concurrency_slot",
                {"side_effect": ConcurrencyLimitExceeded("full")},
                status.HTTP_429_TOO_MANY_REQUESTS,
            ),
            (
                "organization_without_a_free_query_slot",
                "organization",
                "products.product_analytics.backend.presentation.query_concurrency.app_org_concurrency_slot",
                {"side_effect": ConcurrencyLimitExceeded("full")},
                status.HTTP_429_TOO_MANY_REQUESTS,
            ),
        ]
    )
    def test_stops_a_count_it_cannot_run_now(
        self, _name: str, scope: str, target: str, patch_kwargs: dict, expected_status: int
    ) -> None:
        self._set_membership("organization_admin")
        url = self.url() if scope == "project" else self.organization_url()

        with patch(target, **patch_kwargs):
            response = self.client.get(f"{url}deletion_count/", {"retention_months": 3})

        assert response.status_code == expected_status

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
            for before, after in [(None, 3), (3, 12), (12, None)]:
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
            response = self.client.post(url, {"retention_months": 3}, format="json", HTTP_REFERER="https://[")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[f"{scope}_retention_months"] == 3

    @parameterized.expand([("project",), ("organization",)])
    def test_does_not_track_rolled_back_retention_changes(self, scope: str) -> None:
        self._set_membership("organization_admin")
        url = self.url() if scope == "project" else self.organization_url()

        with patch("posthoganalytics.capture") as capture, self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                response = self.client.post(url, {"retention_months": 3}, format="json")
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
                    self.team, 3, user=self.user, was_impersonated=False, analytics_properties=properties
                )
            else:
                set_organization_events_retention(
                    self.organization, 3, user=self.user, was_impersonated=False, analytics_properties=properties
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
        assert captured["retention_months"] == 3
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


class TestEventsRetentionDeletionCountAPI(ClickhouseTestMixin, APIBaseTest):
    @time_machine.travel("2026-11-05T12:00:00Z", tick=False)
    def test_counts_the_events_the_next_cleanup_deletes(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        own_period_team = Team.objects.create(organization=self.organization, name="Own period")
        TeamEventsRetentionConfig.objects.create(team=own_period_team, events_retention_months=12)
        default_team = Team.objects.create(organization=self.organization, name="Default")
        unset_period_team = Team.objects.create(organization=self.organization, name="Unset period")
        TeamEventsRetentionConfig.objects.create(team=unset_period_team, events_retention_months=None)
        for team, timestamp in [
            (self.team, "2026-08-31T23:59:59Z"),
            (self.team, "2026-09-01T00:00:00Z"),
            (own_period_team, "2026-08-01T00:00:00Z"),
            (default_team, "2026-08-01T00:00:00Z"),
            (unset_period_team, "2026-08-01T00:00:00Z"),
        ]:
            _create_event(team=team, event="$pageview", distinct_id="user", timestamp=timestamp)

        project = self.client.get(f"/api/projects/{self.team.id}/events_retention/deletion_count/?retention_months=3")
        organization = self.client.get(
            f"/api/organizations/{self.organization.id}/events_retention_setting/deletion_count/?retention_months=3"
        )

        assert project.json() == {"retention_months": 3, "events_deleted": 1}
        assert organization.json() == {"retention_months": 3, "events_deleted": 3}

    @time_machine.travel("2026-11-05T12:00:00Z", tick=False)
    def test_counts_the_events_a_downgrade_deletes(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        shorter_period_team = Team.objects.create(organization=self.organization, name="Shorter period")
        TeamEventsRetentionConfig.objects.create(team=shorter_period_team, events_retention_months=12)
        longer_period_team = Team.objects.create(organization=self.organization, name="Longer period")
        TeamEventsRetentionConfig.objects.create(team=longer_period_team, events_retention_months=24)
        for team, timestamp in [
            (self.team, "2026-02-28T23:59:59Z"),
            (self.team, "2026-03-01T00:00:00Z"),
            (shorter_period_team, "2026-01-01T00:00:00Z"),
            (longer_period_team, "2026-01-01T00:00:00Z"),
        ]:
            _create_event(team=team, event="$pageview", distinct_id="user", timestamp=timestamp)

        with override_settings(EVENTS_DATA_RETENTION_ENFORCED=False):
            response = self.client.get(
                f"/api/organizations/{self.organization.id}/events_retention_setting/downgrade_deletion_count/",
                {"retention_months": 12},
            )

        assert response.json() == {"retention_months": 12, "events_deleted": 2}

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
    @time_machine.travel("2100-09-22T20:00:00Z", tick=False)
    def test_members_count_the_events_the_scheduled_deletion_removes(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[{"key": "product_analytics_data_retention", "limit": 2, "unit": "years"}]
        )
        self.team.event_retention_months = 24
        self.team.save()
        self.client.force_login(self.user)
        url = f"/api/projects/{self.team.id}/events_retention/scheduled_deletion_count/"

        nothing_scheduled = self.client.get(url)
        TeamEventsPlanDeletion.objects.create(team=self.team, months=24, next_deletion_on=date(2100, 11, 3))
        for timestamp in ["2098-10-31T23:59:59Z", "2098-11-01T00:00:00Z"]:
            _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp=timestamp)
        scheduled = self.client.get(url)

        assert nothing_scheduled.json() == {"deletes_on": None, "deletes_before": None, "events_deleted": 0}
        assert scheduled.json() == {"deletes_on": "2100-11-03", "deletes_before": "2098-11-01", "events_deleted": 1}

    @parameterized.expand(
        [
            ("project", "scheduled_deletion_count", ["project:read"], status.HTTP_403_FORBIDDEN),
            ("project", "deletion_count", ["project:read"], status.HTTP_403_FORBIDDEN),
            ("project", "deletion_count", ["project:read", "query:read"], status.HTTP_200_OK),
            ("organization", "deletion_count", ["organization:read"], status.HTTP_403_FORBIDDEN),
            ("organization", "deletion_count", ["organization:read", "query:read"], status.HTTP_200_OK),
            ("organization", "downgrade_deletion_count", ["organization:read"], status.HTTP_403_FORBIDDEN),
            ("organization", "downgrade_deletion_count", ["organization:read", "query:read"], status.HTTP_200_OK),
        ]
    )
    def test_tokens_need_query_access_to_count(
        self, scope: str, count: str, scopes: list[str], expected_status: int
    ) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(scopes)}")
        url = (
            f"/api/projects/{self.team.id}/events_retention/"
            if scope == "project"
            else f"/api/organizations/{self.organization.id}/events_retention_setting/"
        )

        response = self.client.get(f"{url}{count}/", {"retention_months": 3})

        assert response.status_code == expected_status
