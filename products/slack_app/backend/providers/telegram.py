"""Telegram implementation of the ``ChatProvider`` seam (central PostHog-owned bot)."""

import hmac
from uuid import UUID

from django.http import HttpRequest

from posthog.models.user import User

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError, ConversationRef
from products.slack_app.backend.services.region_auth import region_claims_secret
from products.slack_app.backend.services.telegram_api import TelegramApiError, TelegramBotClient, telegram_config
from products.slack_app.backend.services.telegram_link import find_linked_telegram_user
from products.slack_app.backend.telegram_thread import _REACTION_EMOJI

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramChatProvider(ChatProvider):
    kind = "telegram"
    integration_kinds = ("telegram",)

    @classmethod
    def validate_webhook(cls, request: HttpRequest) -> None:
        """Telegram echoes the secret we registered with setWebhook verbatim in a
        header. An unconfigured secret rejects everything — the surface stays dark
        until ops provisions it."""
        expected = str(telegram_config()["TELEGRAM_APP_WEBHOOK_SECRET"] or "")
        provided = request.headers.get(TELEGRAM_SECRET_HEADER) or ""
        if not expected or not hmac.compare_digest(expected, provided):
            raise ChatProviderError("Invalid")

    @classmethod
    def region_claims_secret(cls) -> str:
        return region_claims_secret(cls.kind)

    @classmethod
    def find_linked_user(cls, *, external_user_id: str, workspace_id: str, candidate_org_ids: set[UUID]) -> User | None:
        # workspace_id is unused: the bot is central and Telegram user ids are global.
        return find_linked_telegram_user(telegram_user_id=external_user_id, candidate_org_ids=candidate_org_ids)

    def get_user_email(self, external_user_id: str) -> str | None:
        # Telegram exposes no email; identity rests entirely on explicit linking.
        return None

    def post_message(self, ref: ConversationRef, text: str) -> None:
        TelegramBotClient().send_message(chat_id=ref.channel_id, text=text, reply_to_message_id=ref.thread_id)

    def add_reaction(self, ref: ConversationRef, message_id: str, reaction: str) -> None:
        mapped = _REACTION_EMOJI.get(reaction)
        if mapped is None:
            return
        try:
            TelegramBotClient().set_message_reaction(chat_id=ref.channel_id, message_id=message_id, emoji=mapped)
        except TelegramApiError:
            # Reactions are a best-effort nicety; the reply is the real acknowledgement.
            pass

    def collect_thread_messages(self, ref: ConversationRef) -> list[dict[str, str]]:
        # The Bot API has no history-read endpoint; conversation context is limited to
        # the inbound update itself (plus its embedded reply_to_message), which the
        # webhook passes straight into the workflow inputs.
        return []
