import json
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

from products.slack_app.backend.services.telegram_link import user_telegram_integration_from_identity

SECRET = "telegram-webhook-test-secret"
BOT_IDENTITY = {"id": 42, "username": "PostHogBot"}
CHAT_ID = -100555
SENDER_ID = 777001


def _update(
    text: str,
    *,
    update_id: int = 1,
    chat_type: str = "supergroup",
    chat_id: int = CHAT_ID,
    reply_to_bot: bool = False,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 42,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": SENDER_ID, "username": "vojta_tg"},
        "text": text,
    }
    if reply_to_bot:
        message["reply_to_message"] = {"message_id": 41, "from": {"id": BOT_IDENTITY["id"]}, "text": "earlier"}
    return {"update_id": update_id, "message": message}


class TestTelegramEventHandler(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="telegram",
            integration_id=str(CHAT_ID),
            config={"chat_type": "supergroup"},
        )
        self._identity = self.enterContext(
            patch(
                "products.slack_app.backend.views.telegram_events.get_bot_identity",
                return_value=BOT_IDENTITY,
            )
        )
        self._flag = self.enterContext(
            patch(
                "products.slack_app.backend.views.telegram_events.is_telegram_app_enabled",
                return_value=True,
            )
        )
        self._bot_client = self.enterContext(
            patch("products.slack_app.backend.views.telegram_events.TelegramBotClient")
        )
        self._sync_connect = self.enterContext(patch("products.slack_app.backend.views.telegram_events.sync_connect"))
        self._asyncio_run = self.enterContext(patch("products.slack_app.backend.views.telegram_events.asyncio.run"))

    def _link_sender(self) -> None:
        user_telegram_integration_from_identity(
            self.user, telegram_user_id=str(SENDER_ID), telegram_username="vojta_tg"
        )

    def _post(self, update: dict[str, Any], *, secret: str | None = SECRET) -> Any:
        headers = {}
        if secret is not None:
            headers["HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"] = secret
        with override_instance_config("TELEGRAM_APP_WEBHOOK_SECRET", SECRET):
            return self.client.post(
                "/telegram/event-callback/",
                data=json.dumps(update).encode(),
                content_type="application/json",
                **headers,
            )

    def _workflow_started(self) -> bool:
        return self._sync_connect.return_value.start_workflow.called

    @parameterized.expand([("missing", None), ("wrong", "different-secret")])
    def test_rejects_bad_secret_header(self, _name, secret):
        response = self._post(_update("@PostHogBot fix it"), secret=secret)
        assert response.status_code == 403
        assert not self._workflow_started()

    def test_rejects_when_secret_unconfigured(self):
        # Empty setting must fail closed, not accept everything.
        response = self.client.post(
            "/telegram/event-callback/",
            data=json.dumps(_update("@PostHogBot fix it")).encode(),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="",
        )
        assert response.status_code == 403

    def test_duplicate_update_id_dispatches_once(self):
        self._link_sender()
        update = _update("@PostHogBot fix it", update_id=99)

        first = self._post(update)
        second = self._post(update)

        assert first.status_code == 202
        assert second.status_code == 200
        assert self._sync_connect.return_value.start_workflow.call_count <= 1
        assert self._asyncio_run.call_count == 1

    @parameterized.expand(
        [
            ("group_chatter_ignored", "just chatting", "supergroup", False, False),
            ("group_mention_dispatches", "@PostHogBot fix it", "supergroup", False, True),
            ("group_reply_to_bot_dispatches", "please continue", "supergroup", True, True),
            ("dm_dispatches", "fix it", "private", False, True),
        ]
    )
    def test_surface_routing(self, _name, text, chat_type, reply_to_bot, expect_dispatch):
        # Group chatter spawning a workflow per message would be cost and spam;
        # mentions, replies to the bot, and DMs are the whole v1 surface.
        self._link_sender()
        chat_id = CHAT_ID if chat_type == "supergroup" else SENDER_ID
        if chat_type == "private":
            Integration.objects.create(
                team=self.team, kind="telegram", integration_id=str(SENDER_ID), config={"chat_type": "private"}
            )
        update = _update(text, chat_type=chat_type, chat_id=chat_id, reply_to_bot=reply_to_bot)

        response = self._post(update)

        assert response.status_code in (200, 202)
        assert self._asyncio_run.called is expect_dispatch

    def test_unlinked_sender_gets_link_reply_and_no_workflow(self):
        response = self._post(_update("@PostHogBot fix it"))

        assert response.status_code == 200
        assert not self._asyncio_run.called
        reply_text = self._bot_client.return_value.send_message.call_args.kwargs["text"]
        assert "/telegram/link/start/" in reply_text

    def test_flag_off_stays_dark(self):
        self._link_sender()
        self._flag.return_value = False

        response = self._post(_update("@PostHogBot fix it"))

        assert response.status_code == 200
        assert not self._asyncio_run.called
        assert not self._bot_client.return_value.send_message.called

    @patch("products.slack_app.backend.views.telegram_events._proxy_event_to_region")
    @patch("products.slack_app.backend.views.telegram_events._does_other_region_claim_chat", return_value=True)
    @patch("products.slack_app.backend.views.telegram_events.cross_region_routing_enabled", return_value=True)
    def test_unbound_chat_claimed_elsewhere_proxies(self, _routing, _claims, mock_proxy):
        # Telegram delivers every update to one region; an EU-bound chat hitting US
        # must be proxied across or it goes permanently dark.
        mock_proxy.return_value = object()
        self._link_sender()
        update = _update("@PostHogBot fix it", chat_id=-100999)

        response = self._post(update)

        assert response.status_code == 200
        mock_proxy.assert_called_once()
        assert not self._asyncio_run.called
