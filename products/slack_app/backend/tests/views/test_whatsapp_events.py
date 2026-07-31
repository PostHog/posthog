import hmac
import json
import hashlib
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.whatsapp_link import user_whatsapp_integration_from_identity

SECRET = "whatsapp-app-secret"
VERIFY_TOKEN = "whatsapp-verify-token"
WA_ID = "15550001111"


def _message(text: str, *, wamid: str = "wamid.A1", wa_id: str = WA_ID) -> dict[str, Any]:
    return {"from": wa_id, "id": wamid, "timestamp": "0", "type": "text", "text": {"body": text}}


def _payload(messages: list[dict[str, Any]], *, value_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "111222333"},
        "contacts": [{"wa_id": WA_ID, "profile": {"name": "Vojta"}}],
        "messages": messages,
    }
    if value_extra:
        value.update(value_extra)
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}],
    }


class TestWhatsAppEventHandler(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="whatsapp",
            integration_id=WA_ID,
            config={},
        )
        self._flag = self.enterContext(
            patch(
                "products.slack_app.backend.views.whatsapp_events.is_whatsapp_app_enabled",
                return_value=True,
            )
        )
        self._bot_client = self.enterContext(
            patch("products.slack_app.backend.views.whatsapp_events.WhatsAppBotClient")
        )
        self._sync_connect = self.enterContext(patch("products.slack_app.backend.views.whatsapp_events.sync_connect"))
        self._asyncio_run = self.enterContext(patch("products.slack_app.backend.views.whatsapp_events.asyncio.run"))

    def _link_sender(self) -> None:
        user_whatsapp_integration_from_identity(self.user, wa_id=WA_ID, profile_name="Vojta")

    def _post(self, payload: dict[str, Any], *, secret: str | None = SECRET) -> Any:
        body = json.dumps(payload).encode()
        headers: dict[str, Any] = {}
        if secret is not None:
            signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["HTTP_X_HUB_SIGNATURE_256"] = signature
        with override_instance_config("WHATSAPP_APP_APP_SECRET", SECRET):
            return self.client.post(
                "/whatsapp/event-callback/",
                data=body,
                content_type="application/json",
                **headers,
            )

    # --- GET verification handshake ---

    def test_handshake_echoes_challenge_for_matching_token(self):
        with override_instance_config("WHATSAPP_APP_VERIFY_TOKEN", VERIFY_TOKEN):
            response = self.client.get(
                "/whatsapp/event-callback/",
                {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"},
            )
        assert response.status_code == 200
        assert response.content == b"12345"

    @parameterized.expand([("wrong_token", "different"), ("unconfigured", None)])
    def test_handshake_rejects_bad_token(self, _name, configured):
        # An unconfigured verify token must fail closed, not accept everything.
        with override_instance_config("WHATSAPP_APP_VERIFY_TOKEN", configured or ""):
            response = self.client.get(
                "/whatsapp/event-callback/",
                {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"},
            )
        assert response.status_code == 403

    # --- POST events ---

    @parameterized.expand([("missing", None), ("wrong", "different-secret")])
    def test_rejects_bad_signature(self, _name, secret):
        response = self._post(_payload([_message("fix it")]), secret=secret)
        assert response.status_code == 403
        assert not self._asyncio_run.called

    def test_rejects_when_secret_unconfigured(self):
        body = json.dumps(_payload([_message("fix it")])).encode()
        signature = "sha256=" + hmac.new(b"anything", body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/whatsapp/event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        assert response.status_code == 403

    def test_duplicate_wamid_dispatches_once(self):
        self._link_sender()
        payload = _payload([_message("fix it", wamid="wamid.DUP")])

        self._post(payload)
        self._post(payload)

        assert self._asyncio_run.call_count == 1

    def test_statuses_only_payload_is_ignored(self):
        # Delivery/read receipts share the webhook with messages and must not spawn
        # workflows or replies.
        payload = _payload([], value_extra={"statuses": [{"id": "wamid.OUT", "status": "delivered"}]})

        response = self._post(payload)

        assert response.status_code == 200
        assert not self._asyncio_run.called
        assert not self._bot_client.return_value.send_message.called

    def test_link_command_replies_and_starts_no_workflow(self):
        response = self._post(_payload([_message("link some-code")]))

        assert response.status_code == 200
        assert not self._asyncio_run.called
        reply_text = self._bot_client.return_value.send_message.call_args.kwargs["text"]
        assert "expired or was already used" in reply_text

    def test_unlinked_sender_gets_link_reply_and_no_workflow(self):
        response = self._post(_payload([_message("fix it")]))

        assert response.status_code == 200
        assert not self._asyncio_run.called
        reply_text = self._bot_client.return_value.send_message.call_args.kwargs["text"]
        assert "/whatsapp/link/start/" in reply_text

    def test_flag_off_stays_dark(self):
        self._link_sender()
        self._flag.return_value = False

        response = self._post(_payload([_message("fix it")]))

        assert response.status_code == 200
        assert not self._asyncio_run.called
        assert not self._bot_client.return_value.send_message.called

    def test_linked_sender_in_bound_chat_dispatches_workflow(self):
        self._link_sender()

        response = self._post(_payload([_message("fix it")]))

        assert response.status_code == 200
        assert self._asyncio_run.call_count == 1

    @patch("products.slack_app.backend.views.whatsapp_events._proxy_event_to_region")
    @patch("products.slack_app.backend.views.whatsapp_events._does_other_region_claim_chat", return_value=True)
    @patch("products.slack_app.backend.views.whatsapp_events.cross_region_routing_enabled", return_value=True)
    def test_unbound_chat_claimed_elsewhere_proxies(self, _routing, _claims, mock_proxy):
        # Meta delivers every event to one URL; an EU-bound chat hitting US must be
        # proxied across or it goes permanently dark.
        mock_proxy.return_value = object()
        payload = _payload([_message("fix it", wa_id="15559998888", wamid="wamid.EU")])

        response = self._post(payload)

        assert response.status_code == 200
        mock_proxy.assert_called_once()
        assert not self._asyncio_run.called

    @patch("products.slack_app.backend.views.whatsapp_events._proxy_event_to_region", return_value=None)
    @patch("products.slack_app.backend.views.whatsapp_events._does_other_region_claim_chat", return_value=True)
    @patch("products.slack_app.backend.views.whatsapp_events.cross_region_routing_enabled", return_value=True)
    def test_proxy_failure_returns_502_and_unmarks_dedup(self, _routing, _claims, _proxy):
        # Meta retries on non-200; a swallowed dedup mark would turn the retry into
        # a silent drop.
        payload = _payload([_message("fix it", wa_id="15559998888", wamid="wamid.RETRY")])

        first = self._post(payload)
        assert first.status_code == 502

        # The retry must reach the proxy path again instead of being deduped away.
        second = self._post(payload)
        assert second.status_code == 502
