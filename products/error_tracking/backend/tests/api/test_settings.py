from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
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

    def test_update_settings_toggles_autocapture_and_dual_writes_team(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"autocapture_exceptions_opt_in": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["autocapture_exceptions_opt_in"])

        self.assertTrue(ErrorTrackingSettings.objects.get(team=self.team).autocapture_exceptions_opt_in)
        self.team.refresh_from_db()
        self.assertTrue(self.team.autocapture_exceptions_opt_in)

        get_response = self.client.get(f"{self._base_url()}/retrieve_settings/")
        self.assertTrue(get_response.json()["autocapture_exceptions_opt_in"])

    @parameterized.expand(
        [
            ("autocapture_toggle_rebuilds", {"autocapture_exceptions_opt_in": True}, True),
            ("rate_limit_only_does_not", {"project_rate_limit_value": 500}, False),
        ]
    )
    def test_update_settings_dispatches_remote_config_rebuild(self, _name, payload, expects_rebuild):
        with (
            patch("posthog.tasks.remote_config.update_team_remote_config.delay") as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.patch(f"{self._base_url()}/update_settings/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if expects_rebuild:
            # The settings write rebuilds; the Team mirror must not dispatch a second, redundant one.
            self.assertEqual(mock_delay.call_count, 1)
            self.assertEqual(mock_delay.call_args_list[0].args, (self.team.id,))
        else:
            mock_delay.assert_not_called()

    def test_update_settings_logs_activity(self):
        response = self.client.patch(
            f"{self._base_url()}/update_settings/",
            {"autocapture_exceptions_opt_in": True, "project_rate_limit_value": 100},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.get(team_id=self.team.id, scope="ErrorTrackingSettings")
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.user, self.user)
        assert log.detail is not None
        changed_fields = {change["field"] for change in log.detail["changes"]}
        self.assertEqual(changed_fields, {"autocapture_exceptions_opt_in", "project_rate_limit_value"})

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
