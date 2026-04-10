"""Tests for bi-directional Customer.io unsubscribe sync.

Covers:
- The webhook endpoint (signature verification, unsubscribe handling, non-unsubscribe metrics)
- The outbound sync service (no-op when not configured, pushes when configured)
- The hook in ``posthog/views.py`` that fires outbound sync from the preferences page and
  the update endpoint — we assert ``push_unsubscribe_to_customerio`` is called exactly when
  the recipient is globally opted out.
"""

import hmac
import json
import time
import hashlib

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from parameterized import parameterized
from requests import Response

import posthog.plugins.plugin_server_api as plugin_server_api
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.customerio_sync_service import (
    CUSTOMERIO_INTEGRATION_KIND,
    CustomerIOSyncConfig,
    get_sync_config,
    push_unsubscribe_to_customerio,
    record_inbound_unsubscribe,
)


def _mock_response(status_code: int, response_json: dict):
    response = Response()
    response.status_code = status_code
    response.json = lambda: response_json  # type: ignore
    return response


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        b"v0:" + timestamp.encode("utf-8") + b":" + body,
        hashlib.sha256,
    ).hexdigest()


class TestCustomerIOWebhook(BaseTest):
    """The incoming webhook at /webhooks/customerio/<team_id>/."""

    def setUp(self):
        super().setUp()
        self.signing_secret = "whsec_test_shared_secret"
        self.integration = Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "cio-site-id", "region": "us"},
            sensitive_config={
                "track_api_key": "cio-track-key",
                "webhook_signing_secret": self.signing_secret,
            },
        )
        self.client = Client()
        self.url = f"/webhooks/customerio/{self.team.id}/"

    def _post(self, payload: dict, *, secret: str | None = None, timestamp: str | None = None):
        """POST a JSON payload to the webhook with a valid (or overridable) signature."""
        raw = json.dumps(payload).encode("utf-8")
        ts = timestamp if timestamp is not None else str(int(time.time()))
        sig = _sign(secret if secret is not None else self.signing_secret, ts, raw)
        return self.client.post(
            self.url,
            data=raw,
            content_type="application/json",
            HTTP_X_CIO_TIMESTAMP=ts,
            HTTP_X_CIO_SIGNATURE=sig,
        )

    def test_returns_404_when_no_integration_configured(self):
        self.integration.delete()
        response = self._post({"metric": "unsubscribed", "data": {"email_address": "a@b.co"}})
        self.assertEqual(response.status_code, 404)

    def test_returns_404_when_webhook_secret_missing(self):
        self.integration.sensitive_config = {"track_api_key": "only"}
        self.integration.save()
        response = self._post({"metric": "unsubscribed", "data": {"email_address": "a@b.co"}})
        self.assertEqual(response.status_code, 404)

    def test_rejects_bad_signature(self):
        response = self._post(
            {"metric": "unsubscribed", "data": {"email_address": "a@b.co"}},
            secret="wrong-secret",
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(MessageRecipientPreference.objects.filter(team=self.team, identifier="a@b.co").exists())

    def test_rejects_stale_timestamp(self):
        stale = str(int(time.time()) - 3600)
        response = self._post(
            {"metric": "unsubscribed", "data": {"email_address": "a@b.co"}},
            timestamp=stale,
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_missing_signature_headers(self):
        response = self.client.post(
            self.url,
            data=b'{"metric":"unsubscribed"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_unsubscribe_metric_records_optout(self):
        response = self._post(
            {
                "metric": "unsubscribed",
                "event_id": "evt_123",
                "timestamp": int(time.time()),
                "data": {
                    "email_address": "recipient@example.com",
                    "customer_id": "user_42",
                    "identifiers": {"email": "recipient@example.com", "id": "user_42"},
                },
            }
        )
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="recipient@example.com")
        self.assertEqual(
            recipient.preferences.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID),
            PreferenceStatus.OPTED_OUT.value,
        )

    def test_unsubscribe_is_idempotent(self):
        payload = {
            "metric": "unsubscribed",
            "data": {"identifiers": {"email": "dup@example.com"}},
        }
        self.assertEqual(self._post(payload).status_code, 200)
        self.assertEqual(self._post(payload).status_code, 200)
        self.assertEqual(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="dup@example.com").count(),
            1,
        )

    def test_falls_back_to_email_address_when_identifiers_missing(self):
        response = self._post({"metric": "unsubscribed", "data": {"email_address": "fallback@example.com"}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="fallback@example.com").exists()
        )

    def test_missing_identifier_returns_400(self):
        response = self._post({"metric": "unsubscribed", "data": {}})
        self.assertEqual(response.status_code, 400)

    @parameterized.expand(["delivered", "opened", "clicked", "bounced", "complained"])
    def test_non_unsubscribe_metrics_are_ignored(self, metric):
        response = self._post({"metric": metric, "data": {"email_address": "x@y.com"}})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ignored")
        self.assertEqual(body["metric"], metric)
        self.assertFalse(MessageRecipientPreference.objects.filter(team=self.team, identifier="x@y.com").exists())

    def test_invalid_json_returns_400(self):
        ts = str(int(time.time()))
        sig = _sign(self.signing_secret, ts, b"not-json")
        response = self.client.post(
            self.url,
            data=b"not-json",
            content_type="application/json",
            HTTP_X_CIO_TIMESTAMP=ts,
            HTTP_X_CIO_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 400)


class TestCustomerIOSyncService(BaseTest):
    """Unit tests for the outbound sync helpers."""

    def test_get_sync_config_returns_none_when_missing(self):
        self.assertIsNone(get_sync_config(self.team.id))

    def test_sync_config_outbound_enabled_requires_both_credentials(self):
        integration = Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "s"},
            sensitive_config={},
        )
        config = CustomerIOSyncConfig(integration=integration)
        self.assertFalse(config.outbound_enabled)

        integration.sensitive_config = {"track_api_key": "k"}
        integration.save()
        config = CustomerIOSyncConfig(integration=Integration.objects.get(pk=integration.pk))
        self.assertTrue(config.outbound_enabled)

    def test_push_unsubscribe_no_config_is_noop(self):
        """No integration → returns False, no exception."""
        self.assertFalse(push_unsubscribe_to_customerio(self.team.id, "a@b.co"))

    def test_push_unsubscribe_missing_identifier_is_noop(self):
        Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "s"},
            sensitive_config={"track_api_key": "k"},
        )
        self.assertFalse(push_unsubscribe_to_customerio(self.team.id, ""))

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_push_unsubscribe_calls_track_client_when_configured(self, mock_client_cls):
        Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "site", "region": "eu"},
            sensitive_config={"track_api_key": "key"},
        )
        instance = mock_client_cls.return_value

        ok = push_unsubscribe_to_customerio(self.team.id, "person@example.com")

        self.assertTrue(ok)
        mock_client_cls.assert_called_once_with(site_id="site", track_api_key="key", region="eu")
        instance.set_unsubscribed.assert_called_once_with("person@example.com", unsubscribed=True)

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_push_unsubscribe_swallows_client_errors(self, mock_client_cls):
        from products.messaging.backend.services.customerio_client import CustomerIOAPIError

        Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "s"},
            sensitive_config={"track_api_key": "k"},
        )
        mock_client_cls.return_value.set_unsubscribed.side_effect = CustomerIOAPIError("boom")

        # Must not raise — outbound sync is fire-and-forget.
        self.assertFalse(push_unsubscribe_to_customerio(self.team.id, "a@b.co"))

    def test_record_inbound_unsubscribe_creates_row(self):
        recipient = record_inbound_unsubscribe(team_id=self.team.id, identifier="new@example.com")
        self.assertEqual(
            recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID],
            PreferenceStatus.OPTED_OUT.value,
        )

    def test_record_inbound_unsubscribe_preserves_existing_category_prefs(self):
        cat = MessageCategory.objects.create(team=self.team, key="newsletter", name="Newsletter")
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="existing@example.com",
            preferences={str(cat.id): PreferenceStatus.OPTED_IN.value},
        )
        record_inbound_unsubscribe(team_id=self.team.id, identifier="existing@example.com")
        row = MessageRecipientPreference.objects.get(team=self.team, identifier="existing@example.com")
        # Category-specific toggle should remain untouched; only $all is set to opted-out.
        self.assertEqual(row.preferences[str(cat.id)], PreferenceStatus.OPTED_IN.value)
        self.assertEqual(row.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT.value)

    def test_record_inbound_unsubscribe_requires_identifier(self):
        with self.assertRaises(ValueError):
            record_inbound_unsubscribe(team_id=self.team.id, identifier="")


class TestPreferencesViewOutboundSync(BaseTest):
    """Assert that the unsubscribe views actually fire the outbound sync hook."""

    def setUp(self):
        super().setUp()
        self.category = MessageCategory.objects.create(team=self.team, key="newsletter", name="Newsletter")
        self.category2 = MessageCategory.objects.create(team=self.team, key="updates", name="Updates")
        self.recipient = MessageRecipientPreference.objects.create(
            team=self.team, identifier="test@example.com", preferences={}
        )
        self.client = Client()
        self._token_patch = patch.object(
            plugin_server_api, "generate_messaging_preferences_token", return_value="dummy-token"
        )
        self._token_patch.start()
        self.token = plugin_server_api.generate_messaging_preferences_token(self.team.id, self.recipient.identifier)

    def tearDown(self):
        self._token_patch.stop()
        super().tearDown()

    @patch("posthog.views.push_unsubscribe_to_customerio")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_one_click_unsubscribe_triggers_outbound_sync(self, mock_validate, mock_push):
        mock_validate.return_value = _mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        response = self.client.get(
            reverse("message_preferences", kwargs={"token": self.token}),
            {"one_click_unsubscribe": "1"},
        )
        self.assertEqual(response.status_code, 200)
        mock_push.assert_called_once()
        _, kwargs = mock_push.call_args
        self.assertEqual(kwargs["identifier"], "test@example.com")

    @patch("posthog.views.push_unsubscribe_to_customerio")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_all_opted_out_triggers_outbound_sync(self, mock_validate, mock_push):
        mock_validate.return_value = _mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        data = {
            "token": self.token,
            "preferences[]": [f"{self.category.id}:false", f"{self.category2.id}:false"],
        }
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 200)
        mock_push.assert_called_once()

    @patch("posthog.views.push_unsubscribe_to_customerio")
    @patch("posthog.views.validate_messaging_preferences_token")
    def test_update_preferences_partial_optout_does_not_trigger_sync(self, mock_validate, mock_push):
        """If the recipient is still opted into at least one category we don't push a global
        unsubscribe to Customer.io — it would incorrectly suppress every email."""
        mock_validate.return_value = _mock_response(
            200, {"valid": True, "team_id": self.team.id, "identifier": self.recipient.identifier}
        )
        data = {
            "token": self.token,
            "preferences[]": [f"{self.category.id}:true", f"{self.category2.id}:false"],
        }
        response = self.client.post(reverse("message_preferences_update"), data)
        self.assertEqual(response.status_code, 200)
        mock_push.assert_not_called()


class TestCustomerIOSyncConfigAPI(APIBaseTest):
    """Integration test for the customerio_sync configuration endpoint."""

    def test_get_returns_not_configured_when_no_integration(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_categories/customerio_sync/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["configured"])
        self.assertFalse(body["outbound_enabled"])
        self.assertFalse(body["webhook_configured"])

    def test_post_creates_integration_and_enables_outbound(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/customerio_sync/",
            {
                "site_id": "my-site-id",
                "track_api_key": "my-track-key",
                "webhook_signing_secret": "whsec_abc",
                "region": "eu",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["configured"])
        self.assertTrue(body["outbound_enabled"])
        self.assertTrue(body["webhook_configured"])
        self.assertEqual(body["site_id"], "my-site-id")
        self.assertEqual(body["region"], "eu")
        self.assertIn(f"/webhooks/customerio/{self.team.id}/", body["webhook_url"])

        integration = Integration.objects.get(team=self.team, kind=CUSTOMERIO_INTEGRATION_KIND)
        self.assertEqual(integration.config["site_id"], "my-site-id")
        self.assertEqual(integration.sensitive_config["track_api_key"], "my-track-key")
        self.assertEqual(integration.sensitive_config["webhook_signing_secret"], "whsec_abc")

    def test_post_partial_update_preserves_other_fields(self):
        Integration.objects.create(
            team=self.team,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            config={"site_id": "existing", "region": "us"},
            sensitive_config={"track_api_key": "existing-key", "webhook_signing_secret": "existing-sec"},
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/customerio_sync/",
            {"webhook_signing_secret": "rotated-sec"},
        )
        self.assertEqual(response.status_code, 200)

        integration = Integration.objects.get(team=self.team, kind=CUSTOMERIO_INTEGRATION_KIND)
        self.assertEqual(integration.config["site_id"], "existing")
        self.assertEqual(integration.sensitive_config["track_api_key"], "existing-key")
        self.assertEqual(integration.sensitive_config["webhook_signing_secret"], "rotated-sec")

    def test_post_does_not_leak_secrets_in_response(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_categories/customerio_sync/",
            {"site_id": "s", "track_api_key": "secret-key", "webhook_signing_secret": "secret-hook"},
        )
        self.assertEqual(response.status_code, 200)
        raw = response.content.decode("utf-8")
        self.assertNotIn("secret-key", raw)
        self.assertNotIn("secret-hook", raw)
