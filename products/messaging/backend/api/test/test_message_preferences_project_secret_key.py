from typing import Any
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.messaging.backend.api.message_preferences import MessagingPreferencesProjectSecretKeyTeamBurstThrottle
from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)


class TestMessagePreferencesProjectSecretKeyAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.category = MessageCategory.objects.create(team=self.team, key="newsletter", name="Newsletter")

    def _create_project_secret_key(self, team: Team, scopes: list[str], label: str = "server") -> str:
        token = "phs_" + "a" * 35 + "".join(c for c in label if c.isalnum())
        ProjectSecretAPIKey.objects.create(
            team=team,
            label=label,
            mask_value=f"phs_...{label[:4]}",
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def _sdk_request(self, endpoint: str, authorization: str | None, payload: dict | None = None):
        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": authorization} if authorization else {}
        body = {**(payload or {"identifier": "user@example.com"}), "token": self.team.api_token}
        return self.client.post(
            f"/api/projects/@current/messaging_preferences/{endpoint}/",
            urlencode(body),
            content_type="application/x-www-form-urlencoded",
            **headers,
        )

    @parameterized.expand(
        [
            ("add_opt_out", PreferenceStatus.OPTED_OUT),
            ("remove_opt_out", PreferenceStatus.OPTED_IN),
        ]
    )
    @patch("products.messaging.backend.tasks.sync_preferences_to_customerio")
    def test_sdk_request_writes_the_preference(self, endpoint, expected_status, mock_sync):
        token = self._create_project_secret_key(self.team, ["messaging_preference:write"])

        with self.captureOnCommitCallbacks(execute=True):
            response = self._sdk_request(
                endpoint,
                f"Bearer {token}",
                {"identifier": "user@example.com", "category_key": "newsletter"},
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="user@example.com")
        self.assertEqual(preference.get_preference(str(self.category.id)), expected_status)
        self.assertIsNone(preference.created_by)
        mock_sync.assert_called_once_with(self.team.id, "user@example.com", preference.preferences)

    def test_write_response_returns_the_stored_preferences(self):
        stored_preferences = self._store_opted_out_recipient()
        token = self._create_project_secret_key(self.team, ["messaging_preference:write"])

        response = self._sdk_request(
            "add_opt_out", f"Bearer {token}", {"identifier": "user@example.com", "category_key": "newsletter"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.json()["preferences"],
            {**stored_preferences, str(self.category.id): PreferenceStatus.OPTED_OUT.value},
        )

    def _store_opted_out_recipient(self) -> dict[str, str]:
        other_category = MessageCategory.objects.create(team=self.team, key="product", name="Product")
        stored_preferences = {
            ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value,
            str(other_category.id): PreferenceStatus.OPTED_OUT.value,
        }
        MessageRecipientPreference.objects.create(
            team=self.team, identifier="user@example.com", preferences=stored_preferences
        )
        return stored_preferences

    def test_bulk_opt_outs_record_no_creator(self):
        token = self._create_project_secret_key(self.team, ["messaging_preference:write"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_preferences/bulk_add_opt_outs/",
            {"opt_outs": [{"identifier": "user@example.com"}]},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier="user@example.com")
        self.assertIsNone(preference.created_by)

    @parameterized.expand(
        [
            (["messaging_preference:read"], "opt_outs", status.HTTP_200_OK),
            (["messaging_preference:read"], "export_opt_outs_csv", status.HTTP_200_OK),
            (["messaging_preference:write"], "opt_outs", status.HTTP_200_OK),
            (["messaging_preference:write"], "export_opt_outs_csv", status.HTTP_200_OK),
            (["hog_flow:write"], "opt_outs", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_reading_the_opt_out_list_needs_a_messaging_preference_scope(self, scopes, endpoint, expected_status):
        token = self._create_project_secret_key(self.team, scopes)

        response = self.client.get(
            f"/api/projects/{self.team.id}/messaging_preferences/{endpoint}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand([("generate_link", "post"), ("webhook_url", "get")])
    def test_session_only_actions_reject_project_secret_keys(self, endpoint, http_method):
        token = self._create_project_secret_key(self.team, ["messaging_preference:write"])

        response = self.client.generic(
            http_method.upper(),
            f"/api/projects/{self.team.id}/messaging_preferences/{endpoint}/",
            "{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("does not support project secret API key", response.json()["detail"])

    @parameterized.expand(
        [
            (scopes, endpoint, payload)
            for scopes in (["messaging_preference:read"], ["hog_flow:write"], ["endpoint:read"])
            for endpoint, payload in (
                ("add_opt_out", {"identifier": "user@example.com"}),
                ("remove_opt_out", {"identifier": "user@example.com"}),
                ("bulk_add_opt_outs", {"opt_outs": [{"identifier": "user@example.com"}]}),
            )
        ]
    )
    def test_writing_needs_the_messaging_preference_write_scope(self, scopes, endpoint, payload):
        token = self._create_project_secret_key(self.team, scopes)

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_preferences/{endpoint}/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertFalse(MessageRecipientPreference.objects.filter(identifier="user@example.com").exists())

    def test_project_secret_key_cannot_write_to_another_project(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        token = self._create_project_secret_key(other_team, ["messaging_preference:write"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "user@example.com"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertFalse(MessageRecipientPreference.objects.filter(identifier="user@example.com").exists())

    def test_rejects_a_key_from_another_project_than_the_token_names(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        token = self._create_project_secret_key(other_team, ["messaging_preference:write"])

        response = self._sdk_request("add_opt_out", f"Bearer {token}")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertFalse(MessageRecipientPreference.objects.filter(identifier="user@example.com").exists())

    def test_project_secret_key_cannot_read_another_project_by_its_token(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        MessageRecipientPreference.objects.create(team=other_team, identifier="user@example.com", preferences={})
        token = self._create_project_secret_key(self.team, ["messaging_preference:read"])

        response = self.client.get(
            f"/api/projects/@current/messaging_preferences/opt_outs/?token={other_team.api_token}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    @parameterized.expand(["no_credentials", "project_token_as_bearer", "revoked_key"])
    def test_rejects_requests_without_a_valid_secret_key(self, case):
        if case == "no_credentials":
            authorization = None
        elif case == "project_token_as_bearer":
            authorization = f"Bearer {self.team.api_token}"
        else:
            token = self._create_project_secret_key(self.team, ["messaging_preference:write"])
            ProjectSecretAPIKey.objects.filter(team=self.team).delete()
            authorization = f"Bearer {token}"

        response = self._sdk_request("add_opt_out", authorization)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.content)
        self.assertFalse(MessageRecipientPreference.objects.filter(identifier="user@example.com").exists())

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch.object(MessagingPreferencesProjectSecretKeyTeamBurstThrottle, "rate", "1/minute")
    def test_project_secret_keys_share_one_rate_limit_per_project(self, _rate_limit_enabled):
        cache.clear()
        first_key = self._create_project_secret_key(self.team, ["messaging_preference:write"], label="first")
        second_key = self._create_project_secret_key(self.team, ["messaging_preference:write"], label="second")

        first_response = self._sdk_request("add_opt_out", f"Bearer {first_key}")
        second_response = self._sdk_request("add_opt_out", f"Bearer {second_key}")

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED, first_response.content)
        self.assertEqual(second_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
