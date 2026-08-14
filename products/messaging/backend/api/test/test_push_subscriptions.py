import gzip
import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import Client

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.team.team_caching import set_team_in_cache

from products.messaging.backend.api import push_subscriptions
from products.messaging.backend.api.push_identity_tokens import sign_push_identity_token, sign_push_identity_token_es256


def _es256_keypair() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


class TestPushSubscriptionsAPI(BaseTest):
    # Realistic length (>= 32 bytes) so signing/verification exercises a real phs_ secret.
    SECRET = "phs_project_secret_0123456789abcdef0123"

    UNCONFIGURED_PAYLOAD = {
        "distinct_id": "user-1",
        "device_token": "device-token",
        "platform": "android",
        "app_id": "nonexistent-project",
    }

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
        self._clear_unconfigured_throttle()

    def _clear_unconfigured_throttle(self):
        # The throttle counter lives in the cache, which no transaction rolls back and which every test
        # in the process shares. Tests here reuse one team id, so without this a test that trips the
        # throttle would leak 429s into whichever test runs next in the same window.
        cache.clear()

    def _post(self, data: dict, api_key: str | None = None):
        payload = {**data, "api_key": api_key or self.team.api_token}
        return self.client.post(
            "/api/push_subscriptions/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _delete(self, data: dict, api_key: str | None = None):
        payload = {**data, "api_key": api_key or self.team.api_token}
        return self.client.delete(
            "/api/push_subscriptions/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _enable_identity_verification(self, mode: str):
        self.firebase_integration.config["push_identity_verification"] = mode
        self.firebase_integration.save()
        self.team.secret_api_token = self.SECRET
        self.team.save()
        # The endpoint resolves the team from the token cache, so refresh it with the secret set.
        set_team_in_cache(self.team.api_token, self.team)

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

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_unregister_unsets_the_subscription_property(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._delete(
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
        # Unregister clears the property instead of storing a token.
        assert call_kwargs["properties"] == {"$unset": ["$device_push_subscription_my-firebase-project"]}

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_unregister_ios_token(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)

        response = self._delete(
            {
                "distinct_id": "user-1",
                "device_token": "apns-device-token-abc",
                "platform": "ios",
                "app_id": "com.example.app",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["properties"]["$unset"] == ["$device_push_subscription_com.example.app"]

    def test_unregister_integration_not_found(self):
        response = self._delete(
            {
                "distinct_id": "user-1",
                "device_token": "device-token",
                "platform": "android",
                "app_id": "nonexistent-project",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["detail"].lower()

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

    @parameterized.expand(
        [
            (push_subscriptions._UNCONFIGURED_THROTTLE_LIMIT, status.HTTP_400_BAD_REQUEST),
            (push_subscriptions._UNCONFIGURED_THROTTLE_LIMIT + 1, status.HTTP_429_TOO_MANY_REQUESTS),
        ]
    )
    def test_repeated_unconfigured_registrations_are_throttled(self, attempts: int, expected_status: int):
        for _ in range(attempts - 1):
            self._post({**self.UNCONFIGURED_PAYLOAD})

        response = self._post({**self.UNCONFIGURED_PAYLOAD})

        assert response.status_code == expected_status

    def test_throttled_rejection_advertises_retry_after(self):
        for _ in range(push_subscriptions._UNCONFIGURED_THROTTLE_LIMIT + 1):
            response = self._post({**self.UNCONFIGURED_PAYLOAD})

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response["Retry-After"] == str(push_subscriptions._UNCONFIGURED_THROTTLE_WINDOW_SECONDS)

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_configured_app_is_never_throttled(self, mock_capture: MagicMock):
        # The throttle guards the rejection path only. If it were hoisted above the integration lookup
        # it would start 429ing real device registrations once a busy project crossed the limit.
        mock_capture.return_value = MagicMock(status_code=200)

        for _ in range(push_subscriptions._UNCONFIGURED_THROTTLE_LIMIT + 5):
            response = self._post(
                {
                    "distinct_id": "user-1",
                    "device_token": "fcm-device-token-abc",
                    "platform": "android",
                    "app_id": "my-firebase-project",
                }
            )
            assert response.status_code == status.HTTP_200_OK

    def test_unconfigured_app_is_logged_once_per_window(self):
        # The log names the project behind a flood, so it has to survive. It also has to stay bounded:
        # a line per rejection would put one line per device launch into Loki, which is the noise this
        # endpoint already generates.
        with capture_logs() as logs:
            for _ in range(push_subscriptions._UNCONFIGURED_THROTTLE_LIMIT + 5):
                self._post({**self.UNCONFIGURED_PAYLOAD})

        unconfigured_logs = [log for log in logs if log["event"] == "push_subscription_unconfigured"]
        assert len(unconfigured_logs) == 1
        assert unconfigured_logs[0]["team_id"] == self.team.id
        assert unconfigured_logs[0]["app_id"] == "nonexistent-project"

    @patch("products.messaging.backend.api.push_subscriptions.cache")
    def test_throttle_fails_open_when_the_cache_is_unavailable(self, mock_cache: MagicMock):
        # Failing closed here would turn a cache outage into a 500 on a public endpoint.
        mock_cache.incr.side_effect = Exception("cache down")

        response = self._post({**self.UNCONFIGURED_PAYLOAD})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "integration_not_found"

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

    def _register_public_key(self, mode: str, public_pem: str):
        self.firebase_integration.config["push_identity_verification"] = mode
        self.firebase_integration.config["push_identity_public_keys"] = [public_pem]
        self.firebase_integration.save()
        # No shared secret is set: ES256 must verify on the public key alone.
        set_team_in_cache(self.team.api_token, self.team)

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_accepts_an_es256_token_signed_by_the_registered_public_key(self, mock_capture: MagicMock):
        # End to end through the endpoint: the integration holds only the EC public key, the device
        # presents a token its backend signed with the private key, and registration succeeds. Guards
        # that the endpoint gathers config["push_identity_public_keys"] and threads them into
        # verification; the verifier's ES256 path is unit-tested, but nothing else drives it over HTTP.
        mock_capture.return_value = MagicMock(status_code=200)
        private_pem, public_pem = _es256_keypair()
        self._register_public_key("required", public_pem)
        token = sign_push_identity_token_es256(private_pem, "user-1", "my-firebase-project")

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
        assert response.json()["code"] == "identity_verification_failed"
        mock_capture.assert_not_called()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_rejects_a_token_minted_for_another_distinct_id(self, mock_capture: MagicMock):
        # The takeover guard: a token the attacker legitimately minted for their own distinct_id
        # cannot authorize binding a device to the victim's distinct_id.
        self._enable_identity_verification("required")
        attacker_token = sign_push_identity_token(self.SECRET, "attacker", "my-firebase-project")

        response = self._post(
            {
                "distinct_id": "victim",
                "device_token": "fcm-device-token-abc",
                "platform": "android",
                "app_id": "my-firebase-project",
                "identity_token": attacker_token,
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_capture.assert_not_called()

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_optional_mode_stores_even_without_a_token(self, mock_capture: MagicMock):
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

    @patch("products.messaging.backend.api.push_subscriptions.capture_internal")
    def test_required_mode_rejects_unregister_without_a_token(self, mock_capture: MagicMock):
        self._enable_identity_verification("required")

        response = self._delete(
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
    def test_required_mode_accepts_a_valid_token_for_unregister(self, mock_capture: MagicMock):
        mock_capture.return_value = MagicMock(status_code=200)
        self._enable_identity_verification("required")
        token = sign_push_identity_token(self.SECRET, "user-1", "my-firebase-project")

        response = self._delete(
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
    def test_strictest_mode_wins_when_two_integrations_share_an_app_id(self, mock_capture: MagicMock):
        # project_id/bundle_id aren't unique, so an app_id can match several integrations. Resolution
        # must fail closed: a second integration with the same project_id and verification disabled
        # must not let a token-less request through when a sibling requires verification.
        self._enable_identity_verification("required")
        Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="my-firebase-project-duplicate",
            config={"project_id": "my-firebase-project", "push_identity_verification": "disabled"},
            sensitive_config={},
        )

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
