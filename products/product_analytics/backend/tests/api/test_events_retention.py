from datetime import date

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.events_plan_deletion import TeamEventsPlanDeletion
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, TeamEventsRetentionConfig
from posthog.models.organization import OrganizationMembership
from posthog.models.team.event_retention import EVENTS_DATA_RETENTION_FLAG

from products.access_control.backend.facade.testing import create_access_control


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
            "retention_months_choices": [1, 3, 12],
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
            ("longer_than_the_plan", "organization_admin", 60, status.HTTP_400_BAD_REQUEST),
            ("shorter_than_the_staff_minimum", "organization_admin", 3, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 3, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_a_project_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, min_events_retention_months=6)

        response = self.client.post(self.url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()

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
            "retention_months_choices": [1, 3, 12, 24],
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
            ("only_a_project_admin", "project_admin", 3, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_an_organization_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, max_events_retention_months=12)

        response = self.client.post(self.organization_url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert (
            OrganizationEventsRetentionConfig.objects.get(
                organization=self.organization
            ).default_events_retention_months
            is None
        )

    @parameterized.expand(
        [
            ("project_not_a_choice", "project", False, 6, status.HTTP_400_BAD_REQUEST),
            ("organization_not_a_choice", "organization", False, 6, status.HTTP_400_BAD_REQUEST),
            ("project_staff", "project", True, 6, status.HTTP_200_OK),
            ("organization_staff", "organization", True, 6, status.HTTP_200_OK),
            ("staff_longer_than_the_plan", "project", True, 36, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_only_staff_set_a_window_outside_the_choices(
        self, _name: str, scope: str, is_staff: bool, months: int, expected_status: int
    ) -> None:
        self._set_membership("organization_admin")
        self.user.is_staff = is_staff
        self.user.save()
        url = self.url() if scope == "project" else self.organization_url()

        response = self.client.post(url, {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        if expected_status == status.HTTP_200_OK:
            assert response.json()[f"{scope}_retention_months"] == months
        elif not is_staff:
            assert response.json()["detail"] == (
                "Events retention has to be 1, 3, 12 or 24 months. Only PostHog staff can set other values."
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

    @parameterized.expand([("patch",), ("put",), ("delete",)])
    def test_rejects_other_writes(self, method: str) -> None:
        self._set_membership("organization_admin")

        for url in (self.url(), self.organization_url()):
            response = getattr(self.client, method)(url, {"retention_months": 1})

            assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
@time_machine.travel("2026-11-04T12:00:00Z", tick=False)
class TestEventsRetentionImpactAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        # The current window is shorter than every window counted below, so a count that the query floor cuts short
        # reads as zero.
        TeamEventsRetentionConfig.objects.create(team=self.team, events_retention_months=1)
        self.other_team = self.create_team_with_organization(organization=self.organization)
        for timestamp in ("2024-06-15", "2025-09-15", "2025-10-31", "2026-07-15", "2026-10-15"):
            _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp=timestamp)
        _create_event(team=self.other_team, event="$pageview", distinct_id="user", timestamp="2024-06-15")
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("one_month", 1, 4),
            ("three_months", 3, 4),
            ("one_year", 12, 3),
            ("two_years", 24, 1),
            ("seven_years", 84, 0),
        ]
    )
    def test_counts_the_project_events_that_deletion_would_remove(
        self, _name: str, months: int, expected_count: int
    ) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/events_retention/impact/?retention_months={months}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"retention_months": months, "events_deleted": expected_count}

    def test_counts_the_organization_events_only_for_projects_using_its_window(self) -> None:
        response = self.client.get(
            f"/api/organizations/{self.organization.id}/events_retention_setting/impact/?retention_months=24"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"retention_months": 24, "events_deleted": 1}

    def test_reuses_a_cached_count(self) -> None:
        url = f"/api/projects/{self.team.id}/events_retention/impact/?retention_months=12"
        self.client.get(url)
        _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp="2025-01-15")
        flush_persons_and_events()

        response = self.client.get(url)

        assert response.json()["events_deleted"] == 3

    def test_rejects_a_missing_window(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/events_retention/impact/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
