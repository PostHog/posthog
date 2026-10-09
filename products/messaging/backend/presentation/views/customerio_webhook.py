import json
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import WebhookSignatureAuthentication
from posthog.models.integration import Integration

from products.messaging.backend.facade.customerio import (
    record_global_resubscribe,
    record_global_unsubscribe,
    record_topic_preferences,
    webhook_signing_secret,
)


class CustomerIOWebhookAuthentication(WebhookSignatureAuthentication):
    """Customer.io HMAC-SHA256 webhook verification."""

    _team_id: int | None = None
    _integration_id: int | None = None

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
        found = webhook_signing_secret(team_id)
        if found is None:
            return None
        self._team_id = team_id
        self._integration_id = found.integration_id
        return found.secret

    def get_auth_context(self, request: Request) -> Any:
        if self._integration_id is None:
            return None
        return Integration.objects.filter(team_id=self._team_id, pk=self._integration_id).first()


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
        record_global_unsubscribe(team_id, email)

    def _handle_global_resubscribe(self, team_id: int, email: str) -> None:
        record_global_resubscribe(team_id, email)

    def _handle_preferences_changed(self, team_id: int, email: str, data: dict) -> None:
        content_str = data.get("content", "")
        if not content_str:
            return

        content = json.loads(content_str)

        topics: dict = content.get("topics", {})
        if not topics:
            return

        record_topic_preferences(team_id, email, topics)
