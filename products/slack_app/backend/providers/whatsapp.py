"""WhatsApp implementation of the ``ChatProvider`` seam (central PostHog-owned number)."""

import hmac
import hashlib
from uuid import UUID

from django.http import HttpRequest

from posthog.models.user import User

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError, ConversationRef
from products.slack_app.backend.services.region_auth import region_claims_secret
from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, WhatsAppBotClient, whatsapp_config
from products.slack_app.backend.services.whatsapp_link import find_linked_whatsapp_user
from products.slack_app.backend.whatsapp_thread import _REACTION_EMOJI

WHATSAPP_SIGNATURE_HEADER = "X-Hub-Signature-256"


class WhatsAppChatProvider(ChatProvider):
    kind = "whatsapp"
    integration_kinds = ("whatsapp",)

    @classmethod
    def validate_webhook(cls, request: HttpRequest) -> None:
        """Meta signs the raw POST body with the app secret (HMAC-SHA256, hex, prefixed
        ``sha256=``). An unconfigured secret rejects everything — the surface stays
        dark until ops provisions it."""
        secret = str(whatsapp_config()["WHATSAPP_APP_APP_SECRET"] or "")
        provided = request.headers.get(WHATSAPP_SIGNATURE_HEADER) or ""
        if not secret or not provided.startswith("sha256="):
            raise ChatProviderError("Invalid")
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, provided):
            raise ChatProviderError("Invalid")

    @classmethod
    def region_claims_secret(cls) -> str:
        return region_claims_secret(cls.kind)

    @classmethod
    def find_linked_user(cls, *, external_user_id: str, workspace_id: str, candidate_org_ids: set[UUID]) -> User | None:
        # workspace_id is unused: the bot is central and wa_ids (phone numbers) are global.
        return find_linked_whatsapp_user(wa_id=external_user_id, candidate_org_ids=candidate_org_ids)

    def get_user_email(self, external_user_id: str) -> str | None:
        # WhatsApp exposes no email; identity rests entirely on explicit linking.
        return None

    def post_message(self, ref: ConversationRef, text: str) -> None:
        WhatsAppBotClient().send_message(to=ref.channel_id, text=text, reply_to_message_id=ref.thread_id)

    def add_reaction(self, ref: ConversationRef, message_id: str, reaction: str) -> None:
        mapped = _REACTION_EMOJI.get(reaction)
        if mapped is None:
            return
        try:
            WhatsAppBotClient().send_reaction(to=ref.channel_id, message_id=message_id, emoji=mapped)
        except WhatsAppApiError:
            # Reactions are a best-effort nicety; the reply is the real acknowledgement.
            pass

    def collect_thread_messages(self, ref: ConversationRef) -> list[dict[str, str]]:
        # The Cloud API has no history-read endpoint; conversation context is limited
        # to the inbound message itself, which the webhook passes straight into the
        # workflow inputs.
        return []
