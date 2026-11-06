from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSettings
from products.error_tracking.backend.presentation.views.settings import ErrorTrackingSettingsSerializer
from products.error_tracking.backend.tests.auto_resolve_fixtures import create_issue_with_exceptions


class TestErrorTrackingSettingsAPI(APIBaseTest):
    def _base_url(self) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/settings"

    def _personal_api_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    def test_retrieve_settings_with_session_auth(self):
        response = self.client.get(f"{self._base_url()}/retrieve_settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("project_rate_limit_value", response.json())
        self.assertIn("per_issue_rate_limit_value", response.json())
        self.assertIsNone(response.json()["auto_resolve_after_days"])

    def test_update_settings_with_session_auth(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": 5000, "project_rate_limit_bucket_size_minutes": 60},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["project_rate_limit_value"], 5000)

        settings = ErrorTrackingSettings.objects.get(team=self.team)
        self.assertEqual(settings.project_rate_limit_value, 5000)
        self.assertEqual(settings.project_rate_limit_bucket_size_minutes, 60)

    def test_update_settings_only_changes_provided_fields(self):
        setup_response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": 2000, "per_issue_rate_limit_value": 50},
            format="json",
        )
        self.assertEqual(setup_response.status_code, status.HTTP_200_OK)
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"per_issue_rate_limit_value": 75},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["per_issue_rate_limit_value"], 75)
        self.assertEqual(response.json()["project_rate_limit_value"], 2000)

    @parameterized.expand(
        [
            ("project_rate_limit", "project_rate_limit_value", 1000),
            ("auto_resolve", "auto_resolve_after_days", 14),
        ]
    )
    def test_update_settings_sets_and_clears_with_null(self, _name, field, value):
        setup_response = self.client.patch(f"{self._base_url()}/update_settings/", {field: value}, format="json")
        self.assertEqual(setup_response.status_code, status.HTTP_200_OK)
        self.assertEqual(getattr(ErrorTrackingSettings.objects.get(team=self.team), field), value)
        response = self.client.patch(f"{self._base_url()}/update_settings/", {field: None}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()[field])
        self.assertIsNone(getattr(ErrorTrackingSettings.objects.get(team=self.team), field))

    def test_update_settings_rejects_invalid_auto_resolve_days(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/", {"auto_resolve_after_days": 366}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "auto_resolve_after_days")

    def test_auto_resolve_preview_requires_days_in_range(self):
        response = self.client.get(f"{self._base_url()}/auto_resolve_preview/", {"days": 0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("read_scope", ["error_tracking:read"], status.HTTP_200_OK),
            ("write_scope_satisfies_read", ["error_tracking:write"], status.HTTP_200_OK),
            ("wrong_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_retrieve_settings_personal_api_key_scopes(self, _name, scopes, expected_status):
        value = self._personal_api_key(scopes)
        self.client.logout()
        response = self.client.get(
            f"{self._base_url()}/retrieve_settings/",
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )
        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand(
        [
            ("write_scope", ["error_tracking:write"], status.HTTP_200_OK),
            ("read_scope_insufficient", ["error_tracking:read"], status.HTTP_403_FORBIDDEN),
            ("wrong_scope", ["insight:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_update_settings_personal_api_key_scopes(self, _name, scopes, expected_status):
        value = self._personal_api_key(scopes)
        self.client.logout()
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"per_issue_rate_limit_value": 100},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )
        self.assertEqual(response.status_code, expected_status)


class TestErrorTrackingSettingsSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero", 0, False),
            ("above_max", 366, False),
            ("negative", -7, False),
            ("fraction", 1.5, False),
            ("text", "two weeks", False),
            ("min", 1, True),
            ("max", 365, True),
            ("off", None, True),
        ]
    )
    def test_auto_resolve_after_days(self, _name, value, expected_valid):
        serializer = ErrorTrackingSettingsSerializer(data={"auto_resolve_after_days": value}, partial=True)
        self.assertEqual(serializer.is_valid(), expected_valid, serializer.errors)


class TestErrorTrackingAutoResolvePreviewAPI(ClickhouseTestMixin, APIBaseTest):
    AFTER_DAYS = 14

    def _preview_count(self) -> int:
        response = self.client.get(
            f"/api/projects/{self.team.id}/error_tracking/settings/auto_resolve_preview/",
            {"days": self.AFTER_DAYS},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()["count"]

    @parameterized.expand(
        [
            ("quiet_active", {"exception_days_ago": [[20]]}, 1),
            ("exceptions_past_retention", {"created_days_ago": 400}, 1),
            ("assigned", {"exception_days_ago": [[20]], "assigned": True}, 1),
            ("recent_exception", {"exception_days_ago": [[20, 2]]}, 0),
            ("recent_exception_on_merged_fingerprint", {"exception_days_ago": [[20], [2]]}, 0),
            ("created_recently", {"created_days_ago": 5}, 0),
            ("suppressed", {"status": ErrorTrackingIssue.Status.SUPPRESSED}, 0),
            ("already_resolved", {"status": ErrorTrackingIssue.Status.RESOLVED}, 0),
        ]
    )
    def test_preview_counts_quiet_active_issues(self, _name, issue_kwargs, expected_count):
        kwargs = {key: value for key, value in issue_kwargs.items() if key != "assigned"}
        create_issue_with_exceptions(self.team, assignee=self.user if issue_kwargs.get("assigned") else None, **kwargs)
        self.assertEqual(self._preview_count(), expected_count)

    def test_preview_ignores_other_teams(self):
        create_issue_with_exceptions(self.create_team_with_organization(organization=self.organization))
        self.assertEqual(self._preview_count(), 0)
