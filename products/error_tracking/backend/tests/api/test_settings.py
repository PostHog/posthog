from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

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
        self.assertIs(response.json()["adaptive_ingestion_enabled"], True)

    def test_retrieve_settings_for_existing_project_without_settings(self):
        ErrorTrackingSettings.objects.filter(team=self.team).delete()

        response = self.client.get(f"{self._base_url()}/retrieve_settings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()["adaptive_ingestion_enabled"], False)

    def test_update_settings_with_session_auth(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {
                "project_rate_limit_value": 5000,
                "project_rate_limit_bucket_size_minutes": 60,
                "adaptive_ingestion_enabled": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["project_rate_limit_value"], 5000)
        self.assertIs(response.json()["adaptive_ingestion_enabled"], True)

        settings = ErrorTrackingSettings.objects.get(team=self.team)
        self.assertIs(settings.adaptive_ingestion_enabled, True)
        self.assertIs(
            self.client.get(f"{self._base_url()}/retrieve_settings/").json()["adaptive_ingestion_enabled"], True
        )
        self.assertEqual(settings.project_rate_limit_value, 5000)
        self.assertEqual(settings.project_rate_limit_bucket_size_minutes, 60)

    def test_update_settings_only_changes_provided_fields(self):
        setup_response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": 2000, "per_issue_rate_limit_value": 50, "adaptive_ingestion_enabled": True},
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
