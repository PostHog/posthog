import hmac
import json
import time
import hashlib

from posthog.test.base import APIBaseTest

from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig


class TestCustomerIOWebhook(APIBaseTest):
    SIGNING_SECRET = "test_webhook_secret_123"

    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": self.SIGNING_SECRET},
            created_by=self.user,
        )
        self.config = OptOutSyncConfig.objects.create(
            team=self.team,
            webhook_integration=self.integration,
            webhook_enabled=True,
        )
        self.url = f"/api/environments/{self.team.id}/messaging/customerio/webhook/"

        # Create categories that mimic a Customer.io import (key = "customerio_topic_{id}")
        self.cat_7 = MessageCategory.objects.create(team=self.team, key="customerio_topic_7", name="Product updates")
        self.cat_8 = MessageCategory.objects.create(
            team=self.team, key="customerio_topic_8", name="Marketing newsletter"
        )

    def _sign(self, body: str, secret: str | None = None, ts: int | None = None) -> tuple[str, str]:
        ts = ts or int(time.time())
        secret = secret or self.SIGNING_SECRET
        sig = hmac.new(
            secret.encode(),
            f"v0:{ts}:{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return sig, str(ts)

    def _post_webhook(self, body: dict, signature: str | None = None, timestamp: str | None = None):
        body_str = json.dumps(body)
        if signature is None or timestamp is None:
            sig, ts = self._sign(body_str)
            signature = signature or sig
            timestamp = timestamp or ts
        return self.client.post(
            self.url,
            data=body_str,
            content_type="application/json",
            HTTP_X_CIO_SIGNATURE=signature,
            HTTP_X_CIO_TIMESTAMP=timestamp,
        )

    # ── HMAC verification ──

    def test_bad_signature_rejected(self):
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        body_str = json.dumps(body)
        sig, ts = self._sign(body_str, secret="wrong_secret")

        response = self._post_webhook(body, sig, ts)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="user@example.com").exists()
        )

    def test_missing_both_headers_rejected(self):
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        response = self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_signature_header_rejected(self):
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        response = self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_CIO_TIMESTAMP=str(int(time.time())),
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_timestamp_header_rejected(self):
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        body_str = json.dumps(body)
        sig, _ = self._sign(body_str)
        response = self.client.post(
            self.url,
            data=body_str,
            content_type="application/json",
            HTTP_X_CIO_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 401)

    def test_timestamp_skew_rejected(self):
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        body_str = json.dumps(body)
        sig, ts = self._sign(body_str, ts=int(time.time()) - 600)
        response = self._post_webhook(body, sig, ts)
        self.assertEqual(response.status_code, 401)

    def test_webhook_disabled_rejected(self):
        self.config.webhook_enabled = False
        self.config.save(update_fields=["webhook_enabled"])

        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 401)

    def test_no_integration_rejected(self):
        self.integration.delete()
        body = {"metric": "unsubscribed", "data": {"email_address": "user@example.com"}}
        body_str = json.dumps(body)
        sig, ts = self._sign(body_str)
        response = self._post_webhook(body, sig, ts)
        self.assertEqual(response.status_code, 401)

    def test_cross_team_signature_rejected(self):
        other_team = self.organization.teams.create(name="Other team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": "other_team_secret_456"},
            created_by=self.user,
        )
        OptOutSyncConfig.objects.create(
            team=other_team,
            webhook_integration=other_integration,
            webhook_enabled=True,
        )
        body = {"metric": "unsubscribed", "data": {"email_address": "cross@example.com"}}
        body_str = json.dumps(body)
        sig, ts = self._sign(body_str, secret=self.SIGNING_SECRET)

        self.client.logout()
        response = self.client.post(
            f"/api/environments/{other_team.id}/messaging/customerio/webhook/",
            data=body_str,
            content_type="application/json",
            HTTP_X_CIO_SIGNATURE=sig,
            HTTP_X_CIO_TIMESTAMP=ts,
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=other_team, identifier="cross@example.com").exists()
        )

    def test_missing_email_returns_200_no_side_effects(self):
        body = {"metric": "unsubscribed", "data": {"customer_id": "42"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MessageRecipientPreference.objects.filter(team=self.team).count(), 0)

    def test_hmac_auth_works_without_session(self):
        self.client.logout()
        body = {"metric": "unsubscribed", "data": {"email_address": "unauthed@example.com"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="unauthed@example.com").exists()
        )

    # ── customer_unsubscribed ──

    def test_customer_unsubscribed_records_global_opt_out(self):
        body = {
            "metric": "unsubscribed",
            "event_id": "01E4C4CT6YDC7Y5M7FE1GWWPQJ",
            "object_type": "customer",
            "timestamp": 1613063089,
            "data": {
                "customer_id": "42",
                "email_address": "test@example.com",
                "identifiers": {"id": "42", "email": "test@example.com", "cio_id": "d9c106000001"},
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="test@example.com")
        self.assertEqual(recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT.value)

    def test_customer_unsubscribed_preserves_existing_prefs(self):
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="existing@example.com",
            preferences={str(self.cat_7.id): PreferenceStatus.OPTED_IN.value},
        )
        body = {"metric": "unsubscribed", "data": {"email_address": "existing@example.com"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="existing@example.com")
        self.assertEqual(recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT.value)
        self.assertEqual(recipient.preferences[str(self.cat_7.id)], PreferenceStatus.OPTED_IN.value)

    # ── subscribed (re-subscribe) ──

    def test_subscribed_clears_global_opt_out(self):
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="resubscriber@example.com",
            preferences={ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value},
        )
        body = {"metric": "subscribed", "data": {"email_address": "resubscriber@example.com"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="resubscriber@example.com")
        self.assertNotIn(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, recipient.preferences)

    def test_subscribed_noop_when_not_opted_out(self):
        body = {"metric": "subscribed", "data": {"email_address": "newuser@example.com"}}
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="newuser@example.com")
        self.assertNotIn(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, recipient.preferences)

    # ── cio_subscription_preferences_changed ──

    def test_preferences_changed_opts_out_specific_topics(self):
        body = {
            "metric": "cio_subscription_preferences_changed",
            "event_id": "01E4C4CT6YDC7Y5M7FE1GWWPQJ",
            "object_type_type": "email",
            "timestamp": 1613063089,
            "data": {
                "content": json.dumps({"topics": {"topic_7": False, "topic_8": True}}),
                "customer_id": "42",
                "email_address": "test@example.com",
                "identifiers": {"id": "42", "email": "test@example.com"},
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="test@example.com")
        self.assertEqual(recipient.preferences[str(self.cat_7.id)], PreferenceStatus.OPTED_OUT.value)
        self.assertEqual(recipient.preferences[str(self.cat_8.id)], PreferenceStatus.OPTED_IN.value)
        # Not all opted out → no global opt-out
        self.assertNotIn(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, recipient.preferences)

    def test_preferences_changed_all_false_does_not_set_global_opt_out(self):
        body = {
            "metric": "cio_subscription_preferences_changed",
            "data": {
                "content": json.dumps({"topics": {"topic_7": False, "topic_8": False}}),
                "email_address": "test@example.com",
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="test@example.com")
        self.assertEqual(recipient.preferences[str(self.cat_7.id)], PreferenceStatus.OPTED_OUT.value)
        self.assertEqual(recipient.preferences[str(self.cat_8.id)], PreferenceStatus.OPTED_OUT.value)
        self.assertNotIn(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, recipient.preferences)

    def test_preferences_changed_does_not_touch_global_opt_out(self):
        MessageRecipientPreference.objects.create(
            team=self.team,
            identifier="test@example.com",
            preferences={
                str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value,
                str(self.cat_8.id): PreferenceStatus.OPTED_OUT.value,
                ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value,
            },
        )
        body = {
            "metric": "cio_subscription_preferences_changed",
            "data": {
                "content": json.dumps({"topics": {"topic_7": True, "topic_8": False}}),
                "email_address": "test@example.com",
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

        recipient = MessageRecipientPreference.objects.get(team=self.team, identifier="test@example.com")
        self.assertEqual(recipient.preferences[str(self.cat_7.id)], PreferenceStatus.OPTED_IN.value)
        self.assertEqual(recipient.preferences[str(self.cat_8.id)], PreferenceStatus.OPTED_OUT.value)
        self.assertEqual(recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID], PreferenceStatus.OPTED_OUT.value)

    def test_preferences_changed_unknown_topic_ignored(self):
        body = {
            "metric": "cio_subscription_preferences_changed",
            "data": {
                "content": json.dumps({"topics": {"topic_999": False}}),
                "email_address": "test@example.com",
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)
        # No recipient created since no known topics matched
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="test@example.com")
            .exclude(preferences={})
            .filter(preferences__has_key=ALL_MESSAGE_PREFERENCE_CATEGORY_ID)
            .exists()
        )

    def test_preferences_changed_invalid_content_json_returns_400(self):
        body = {
            "metric": "cio_subscription_preferences_changed",
            "data": {
                "content": "not valid json {{{",
                "email_address": "test@example.com",
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 400)

    def test_preferences_changed_empty_content(self):
        body = {
            "metric": "cio_subscription_preferences_changed",
            "data": {
                "content": "",
                "email_address": "test@example.com",
            },
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)

    def test_unknown_metric_ignored(self):
        body = {
            "metric": "email_opened",
            "data": {"email_address": "test@example.com"},
        }
        response = self._post_webhook(body)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            MessageRecipientPreference.objects.filter(team=self.team, identifier="test@example.com").exists()
        )
