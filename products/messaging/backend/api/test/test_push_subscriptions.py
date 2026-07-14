import gzip
import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.team.team_caching import set_team_in_cache

from products.messaging.backend.api.push_identity_tokens import sign_push_identity_token


class TestPushSubscriptionsAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

        self.firebase_integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="my-firebase-project",
            config={"project_id": "my-firebase-project"},
            sensitive_config={},
        )
        self.apns_integration = Integration.objects.create(
            team=self.team,
            kind="apns",
            integration_id="TEAM123.com.example.app",
            config={"bundle_id": "com.example.app", "team_id": "TEAM123", "key_id": "KEY123"},
            sensitive_config={},
        )

    def _post(self, data: dict, api_key: str | None = None):
        payload = {**data, "api_key": api_key or self.team.api_token}
        return self.client.post(
            "/api/push_subscriptions/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_register_android_token(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["distinct_id"] == "user-1"
        assert data["platform"] == "android"

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["distinct_id"] == "user-1"
        assert call_kwargs["event_name"] == "$set"
        assert call_kwargs["process_person_profile"] is True
        assert "$device_push_subscription_my-firebase-project" in call_kwargs["properties"]["$set"]

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_register_ios_token(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "apns-device-token-abc",
                "platform": "ios",
                "app_id": "com.example.app",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["distinct_id"] == "user-1"
        assert data["platform"] == "ios"

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert "$device_push_subscription_com.example.app" in call_kwargs["properties"]["$set"]

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_ios_device_registers_a_firebase_token(self, mock_capture: MagicMock):
        # An iOS app delivering via Firebase registers with the Firebase project_id even though its
        # platform is "ios": the provider is resolved from the app_id, not the device platform.
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-token-from-ios",
                "platform": "ios",
                "app_id": "my-firebase-project",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        call_kwargs = mock_capture.call_args.kwargs
        assert "$device_push_subscription_my-firebase-project" in call_kwargs["properties"]["$set"]

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_token_is_encrypted(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
            }
        )

        assert response.status_code == status.HTTP_200_OK

        call_kwargs = mock_capture.call_args.kwargs
        encrypted_value = call_kwargs["properties"]["$set"]["$device_push_subscription_my-firebase-project"]
        # The encrypted value should not be the raw token
        assert encrypted_value != "fcm-device-token-abc"
        # It should be a non-empty string (Fernet token)
        assert isinstance(encrypted_value, str)
        assert len(encrypted_value) > 0

    def test_missing_api_key_returns_401(self):
        response = self.client.post(
            "/api/push_subscriptions/",
            data=json.dumps({"distinct_id": "user-1", "device_token": "t", "platform": "android", "app_id": "proj"}),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invalid_token_returns_401(self):
        response = self._post(
            {"distinct_id": "user-1", "device_token": "t", "platform": "android", "app_id": "proj"},
            api_key="phc_invalid_token",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_required_fields(self):
        response = self._post({"distinct_id": "user-1"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "device_token" in response.json()["detail"]
        assert "platform" in response.json()["detail"]
        assert "app_id" in response.json()["detail"]

    def test_invalid_platform(self):
        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "device-token",
                "platform": "windows_phone",
                "app_id": "proj",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid platform" in response.json()["detail"]

    def test_integration_not_found(self):
        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "device-token",
                "platform": "android",
                "app_id": "nonexistent-project",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["detail"].lower()

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        Integration.objects.create(
            team=other_team,
            kind="firebase",
            integration_id="other-project",
            config={"project_id": "other-project"},
            sensitive_config={},
        )

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "device-token",
                "platform": "android",
                "app_id": "other-project",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["detail"].lower()

    def test_get_method_not_allowed(self):
        response = self.client.get(
            f"/api/push_subscriptions/?token={self.team.api_token}",
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_options_returns_200(self):
        response = self.client.options("/api/push_subscriptions/")

        assert response.status_code == status.HTTP_200_OK

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_gzip_compressed_body(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-1",
            "device_token": "fcm-device-token-abc",
            "platform": "android",
            "app_id": "my-firebase-project",
        }
        compressed = gzip.compress(json.dumps(payload).encode())

        response = self.client.post(
            "/api/push_subscriptions/",
            data=compressed,
            content_type="application/json",
            HTTP_CONTENT_ENCODING="gzip",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["distinct_id"] == "user-1"
        mock_capture.assert_called_once()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_oversized_body_is_rejected_before_parsing(self, mock_capture: MagicMock):
        # A body over the cap is rejected before load_data_from_request decompresses it, so a
        # compressed body can't inflate into a memory-exhaustion payload.
        oversized = json.dumps({"api_key": self.team.api_token, "padding": "x" * (16 * 1024 + 1)})

        response = self.client.post(
            "/api/push_subscriptions/",
            data=oversized,
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        mock_capture.assert_not_called()

    SECRET = "phs_project_secret_0123456789abcdef0123"

    def _enable_identity_verification(self, mode: str):
        self.firebase_integration.config["push_identity_verification"] = mode
        self.firebase_integration.save()
        self.team.secret_api_token = self.SECRET
        self.team.save()
        # The endpoint reads the team (and its secret) from cache; refresh it so the secret is present.
        set_team_in_cache(self.team.api_token, self.team)

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_accepts_a_valid_identity_token(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)
        self._enable_identity_verification("required")
        token = sign_push_identity_token(self.SECRET, "user-1", "my-firebase-project")

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
                "identity_token": token,
            }
        )

        assert response.status_code == status.HTTP_200_OK
        mock_capture.assert_called_once()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_rejects_registration_without_a_token(self, mock_capture: MagicMock):
        self._enable_identity_verification("required")

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_capture.assert_not_called()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_rejects_a_token_minted_for_another_distinct_id(self, mock_capture: MagicMock):
        # The rebind attack: an attacker can only mint a token for their own distinct_id, so it can't
        # authorize binding a device under the victim's distinct_id.
        self._enable_identity_verification("required")
        attacker_token = sign_push_identity_token(self.SECRET, "attacker", "my-firebase-project")

        response = self._post(
            {
                "distinct_id": "victim",
                "device_token": "attacker-device-token",
                "platform": "android",
                "app_id": "my-firebase-project",
                "identity_token": attacker_token,
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_capture.assert_not_called()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_optional_mode_stores_even_without_a_token(self, mock_capture: MagicMock):
        # Monitor mode verifies and records the outcome but must not block delivery, so a customer can
        # confirm their backend is minting valid tokens before switching to required.
        mock_capture.return_value = MagicMock(status_code=200)
        self._enable_identity_verification("optional")

        response = self._post(
            {
                "distinct_id": "user-1",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        mock_capture.assert_called_once()
