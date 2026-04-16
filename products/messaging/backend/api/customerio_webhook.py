import json
import logging
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import WebhookSignatureAuthentication
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig

logger = logging.getLogger(__name__)


class CustomerIOWebhookAuthentication(WebhookSignatureAuthentication):
    """Customer.io HMAC-SHA256 webhook verification."""

    _integration: Integration | None = None

    def get_signature_header(self) -> str:
        return "x-cio-signature"

    def get_timestamp_header(self) -> str:
        return "x-cio-timestamp"

    def build_hmac_input(self, timestamp: str, body: str) -> str:
        return f"v0:{timestamp}:{body}"

    def get_signing_secret(self, request: Request) -> str | None:
        team_id = self._get_team_id(request)
        if not team_id:
            return None
        try:
            config = OptOutSyncConfig.objects.select_related("webhook_integration").get(team_id=team_id)
        except OptOutSyncConfig.DoesNotExist:
            return None
        if not config.webhook_enabled or not config.webhook_integration:
            return None
        self._integration = config.webhook_integration
        return self._integration.sensitive_config.get("webhook_signing_secret")

    def get_auth_context(self, request: Request) -> Any:
        return self._integration


class CustomerIOWebhookView(APIView):
    """
    Customer.io reporting webhook endpoint.
    Lives outside TeamAndOrgViewSetMixin because that mixin always appends
    session/JWT auth which external webhooks don't carry.
    """

    authentication_classes = [CustomerIOWebhookAuthentication]
    permission_classes = []

    def post(self, request, team_id: int):
        metric = request.data.get("metric", "")
        data = request.data.get("data", {})
        email = data.get("email_address")

        if not email:
            return Response(status=200)

        try:
            if metric == "cio_subscription_preferences_changed":
                self._handle_preferences_changed(team_id, email, data)
            elif metric == "unsubscribed":
                self._handle_global_unsubscribe(team_id, email)
            elif metric == "subscribed":
                self._handle_global_resubscribe(team_id, email)
        except json.JSONDecodeError:
            return Response({"error": "Malformed JSON in content field"}, status=400)

        return Response(status=200)

    def _handle_global_unsubscribe(self, team_id: int, email: str) -> None:
        recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)
        recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value
        recipient.save(update_fields=["preferences", "updated_at"])

    def _handle_global_resubscribe(self, team_id: int, email: str) -> None:
        recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)
        if ALL_MESSAGE_PREFERENCE_CATEGORY_ID in recipient.preferences:
            del recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
            recipient.save(update_fields=["preferences", "updated_at"])

    def _handle_preferences_changed(self, team_id: int, email: str, data: dict) -> None:
        content_str = data.get("content", "")
        if not content_str:
            return

        content = json.loads(content_str)

        topics: dict = content.get("topics", {})
        if not topics:
            return

        topic_key_to_category: dict[str, str] = {}
        categories = MessageCategory.objects.filter(team_id=team_id, key__startswith="customerio_", deleted=False)
        for cat in categories:
            topic_key = cat.key.removeprefix("customerio_")
            topic_key_to_category[topic_key] = str(cat.id)

        if not topic_key_to_category:
            return

        recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)

        changed = False
        for topic_key, is_subscribed in topics.items():
            category_id = topic_key_to_category.get(topic_key)
            if not category_id:
                logger.warning("customerio_webhook: unknown topic %s for team %s", topic_key, team_id)
                continue

            new_status = PreferenceStatus.OPTED_IN.value if is_subscribed else PreferenceStatus.OPTED_OUT.value
            if recipient.preferences.get(category_id) != new_status:
                recipient.preferences[category_id] = new_status
                changed = True

        if changed:
            recipient.save(update_fields=["preferences", "updated_at"])
