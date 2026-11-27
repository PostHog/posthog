from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_summary_config import ISSUE_SUMMARY_FLAG
from products.error_tracking.backend.models import ErrorTrackingSettings


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
        self.assertIs(response.json()["adaptive_ingestion_enabled"], False)
        self.assertIs(response.json()["ai_issue_summaries_enabled"], False)

    def test_update_settings_with_session_auth(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {
                "project_rate_limit_value": 5000,
                "project_rate_limit_bucket_size_minutes": 60,
                "adaptive_ingestion_enabled": True,
                "ai_issue_summaries_enabled": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["project_rate_limit_value"], 5000)
        self.assertIs(response.json()["adaptive_ingestion_enabled"], True)
        self.assertIs(response.json()["ai_issue_summaries_enabled"], True)

        settings = ErrorTrackingSettings.objects.get(team=self.team)
        self.assertIs(settings.adaptive_ingestion_enabled, True)
        self.assertIs(settings.ai_issue_summaries_enabled, True)
        retrieved = self.client.get(f"{self._base_url()}/retrieve_settings/").json()
        self.assertIs(retrieved["adaptive_ingestion_enabled"], True)
        self.assertIs(retrieved["ai_issue_summaries_enabled"], True)
        self.assertEqual(settings.project_rate_limit_value, 5000)
        self.assertEqual(settings.project_rate_limit_bucket_size_minutes, 60)

    def test_update_settings_only_changes_provided_fields(self):
        setup_response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {
                "project_rate_limit_value": 2000,
                "per_issue_rate_limit_value": 50,
                "adaptive_ingestion_enabled": True,
                "ai_issue_summaries_enabled": True,
            },
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
        self.assertIs(response.json()["adaptive_ingestion_enabled"], True)
        self.assertIs(response.json()["ai_issue_summaries_enabled"], True)

    @parameterized.expand(
        [
            ("turning_on_is_refused", False, True, status.HTTP_400_BAD_REQUEST, False),
            ("turning_off_is_allowed", True, False, status.HTTP_200_OK, False),
        ]
    )
    def test_ai_issue_summaries_without_ai_approval(self, _name, initially, requested, expected_status, stored):
        ErrorTrackingSettings.objects.create(team=self.team, ai_issue_summaries_enabled=initially)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"ai_issue_summaries_enabled": requested},
            format="json",
        )

        self.assertEqual(response.status_code, expected_status, response.json())
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertEqual(response.json()["attr"], "ai_issue_summaries_enabled")
        self.assertIs(ErrorTrackingSettings.objects.get(team=self.team).ai_issue_summaries_enabled, stored)

    def test_update_settings_clears_limit_with_null(self):
        setup_response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": 1000, "adaptive_ingestion_enabled": True},
            format="json",
        )
        self.assertEqual(setup_response.status_code, status.HTTP_200_OK)
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": None, "adaptive_ingestion_enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["project_rate_limit_value"])
        self.assertIs(response.json()["adaptive_ingestion_enabled"], False)

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

    @parameterized.expand(
        [
            ("app_context_flag_on", "/_app_context", True, ["issue_summaries"]),
            ("app_context_flag_off", "/_app_context", False, []),
            ("project_flag_on", "/api/projects/@current/", True, ["issue_summaries"]),
            ("project_flag_off", "/api/projects/@current/", False, []),
        ]
    )
    def test_team_lists_available_ai_features_from_the_local_project_flag(self, _name, url, flag_on, expected):
        enabled_project = str(self.team.id) if flag_on else None

        # Local definitions only: the fake has no remote service to fall back to.
        def local_flags(flag, distinct_id, *, groups, only_evaluate_locally, **_options):
            return only_evaluate_locally and flag == ISSUE_SUMMARY_FLAG and groups == {"project": enabled_project}

        with patch.object(team_flags, "feature_enabled_or_false", new=local_flags):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        team = body["app_context"]["current_team"] if url == "/_app_context" else body
        self.assertEqual(team["available_error_tracking_ai_features"], expected)
