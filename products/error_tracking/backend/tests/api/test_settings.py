from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.error_tracking.backend.facade import contracts
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

    def test_update_settings_clears_limit_with_null(self):
        setup_response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": 1000},
            format="json",
        )
        self.assertEqual(setup_response.status_code, status.HTTP_200_OK)
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"project_rate_limit_value": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["project_rate_limit_value"])

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
            ("read_scope", ["error_tracking:read"], status.HTTP_200_OK),
            ("write_scope_satisfies_read", ["error_tracking:write"], status.HTTP_200_OK),
            ("wrong_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_setup_status_personal_api_key_scopes(self, _name, scopes, expected_status):
        setup_status = contracts.ErrorTrackingSetupStatus(
            project_autocapture_enabled=True,
            remote_config_autocapture_enabled=True,
            has_issues=False,
            recent_data_available=True,
            recent_period_days=7,
            recent_event_count=12,
            recent_exception_count=0,
            last_event_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            last_exception_at=None,
            observed_sdks=[
                contracts.ErrorTrackingObservedSDK(
                    library="posthog-node",
                    event_count=12,
                    latest_version="5.49.0",
                    last_seen_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
                    autocapture_configuration="local",
                    local_option="enableExceptionAutocapture",
                )
            ],
            warnings=[
                contracts.ErrorTrackingSetupWarning(
                    code="node_autocapture_requires_local_configuration",
                    message="Configure exception autocapture in the Node SDK initialization.",
                )
            ],
        )
        value = self._personal_api_key(scopes)
        self.client.logout()

        with patch(
            "products.error_tracking.backend.presentation.views.settings.error_tracking_setup.get_error_tracking_setup_status",
            return_value=setup_status,
        ):
            response = self.client.get(
                f"{self._base_url()}/setup_status/",
                HTTP_AUTHORIZATION=f"Bearer {value}",
            )

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(response.json()["recent_exception_count"], 0)
            self.assertEqual(response.json()["last_event_at"], "2026-08-14T12:00:00Z")
            self.assertEqual(response.json()["observed_sdks"][0]["latest_version"], "5.49.0")
            self.assertEqual(
                response.json()["warnings"][0]["warning_code"],
                "node_autocapture_requires_local_configuration",
            )

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
