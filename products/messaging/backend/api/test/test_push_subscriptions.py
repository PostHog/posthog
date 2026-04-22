import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.team.team import Team


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
