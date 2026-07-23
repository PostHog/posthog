"""Slack implementation of the ``ChatProvider`` seam — pure delegation onto the
existing Slack modules so behavior (and test patch targets) stay where they are."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.http import HttpRequest

from posthog.models import integration as integration_model
from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegrationError
from posthog.models.user import User
from posthog.temporal.ai.slack_app.helpers import safe_react

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError, ConversationRef
from products.slack_app.backend.services.region_auth import region_claims_secret
from products.slack_app.backend.services.slack_messages import collect_thread_messages
from products.slack_app.backend.services.slack_user_info import get_slack_email_for_user
from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user

if TYPE_CHECKING:
    from posthog.models.integration import SlackIntegration


class SlackChatProvider(ChatProvider):
    kind = "slack"
    integration_kinds = SLACK_INTEGRATION_KINDS

    def __init__(self, integration: Integration) -> None:
        super().__init__(integration)
        # ``SlackIntegration`` is resolved through the module at call time — the
        # long-standing test seam patches ``posthog.models.integration.SlackIntegration``,
        # and an import-time binding here would sail past those patches. The constructor
        # also validates the integration kind, so a mis-routed row fails fast.
        self._slack: SlackIntegration = integration_model.SlackIntegration(integration)

    @classmethod
    def validate_webhook(cls, request: HttpRequest) -> None:
        try:
            integration_model.SlackIntegration.validate_request(request)
        except SlackIntegrationError as e:
            raise ChatProviderError(str(e)) from e

    @classmethod
    def region_claims_secret(cls) -> str:
        return region_claims_secret(cls.kind)

    @classmethod
    def find_linked_user(cls, *, external_user_id: str, workspace_id: str, candidate_org_ids: set[UUID]) -> User | None:
        return find_linked_posthog_user(
            slack_user_id=external_user_id,
            slack_team_id=workspace_id,
            candidate_org_ids=candidate_org_ids,
        )

    def get_user_email(self, external_user_id: str) -> str | None:
        return get_slack_email_for_user(self.integration, external_user_id)

    def post_message(self, ref: ConversationRef, text: str) -> None:
        self._slack.client.chat_postMessage(channel=ref.channel_id, thread_ts=ref.thread_id, text=text)

    def add_reaction(self, ref: ConversationRef, message_id: str, reaction: str) -> None:
        safe_react(self._slack.client, ref.channel_id, message_id, reaction)

    def collect_thread_messages(self, ref: ConversationRef) -> list[dict[str, str]]:
        our_bot_id = self._slack.client.auth_test().get("bot_id")
        return collect_thread_messages(self._slack, self.integration, ref.channel_id, ref.thread_id, our_bot_id)
