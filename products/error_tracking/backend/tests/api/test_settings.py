import json
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.event_ingestion_restriction_config import (
    DYNAMIC_CONFIG_REDIS_KEY_PREFIX,
    EventIngestionRestrictionConfig,
    RestrictionType,
)
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.redis import get_client

from products.error_tracking.backend.models import ErrorTrackingSettings

DROP_EVENT_REDIS_KEY = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.DROP_EVENT_FROM_INGESTION}"


class TestErrorTrackingSettingsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        get_client().delete(DROP_EVENT_REDIS_KEY)

    def _base_url(self) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/settings"

    def _drop_event_entries(self) -> list[dict[str, Any]]:
        raw = get_client().get(DROP_EVENT_REDIS_KEY)
        return json.loads(raw) if raw else []

    def _set_ingestion_enabled(self, enabled: bool) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"{self._base_url()}/update_settings/", {"ingestion_enabled": enabled}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["ingestion_enabled"], enabled)

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
        self.assertTrue(response.json()["ingestion_enabled"])

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

    def test_toggling_ingestion_updates_capture_drop_rules(self):
        EventIngestionRestrictionConfig.objects.create(
            token=self.team.api_token,
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["blocked-user"],
            pipelines=["analytics", "errortracking"],
        )

        self._set_ingestion_enabled(False)

        staff_entry, kill_switch_entry = self._drop_event_entries()
        self.assertEqual(staff_entry["distinct_ids"], ["blocked-user"])
        self.assertEqual(
            kill_switch_entry,
            {
                "version": 2,
                "index": 1,
                "token": self.team.api_token,
                "pipelines": ["errortracking"],
                "distinct_ids": [],
                "session_ids": [],
                "event_names": [],
                "event_uuids": [],
                "args": None,
            },
        )

        self._set_ingestion_enabled(True)

        self.assertEqual([entry["distinct_ids"] for entry in self._drop_event_entries()], [["blocked-user"]])

    def test_capture_drop_rule_follows_api_token_rotation(self):
        self._set_ingestion_enabled(False)
        old_token = self.team.api_token

        with self.captureOnCommitCallbacks(execute=True):
            self.team.reset_token_and_save(user=self.user, is_impersonated_session=False)

        self.assertNotEqual(self.team.api_token, old_token)
        self.assertEqual([entry["token"] for entry in self._drop_event_entries()], [self.team.api_token])
