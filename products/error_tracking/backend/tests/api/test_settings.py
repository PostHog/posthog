from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.error_tracking.backend.models import ErrorTrackingSettings
from products.error_tracking.backend.presentation.views.settings import ErrorTrackingSettingsSerializer


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
