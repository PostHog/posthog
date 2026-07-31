"""WhatsApp conversation context and thread handler.

Mirrors ``telegram_thread.py``: WhatsApp chats get the initial ack, relayed agent
messages, and the terminal outcome — nothing in between. Progress and status-stream
methods are no-ops.

One WhatsApp-specific wrinkle: free-form messages are only deliverable inside the
24-hour customer service window opened by the user's last inbound message. A terminal
update landing outside the window fails with a distinct error code; v1 drops it with
a dedicated log key rather than falling back to a template message.
"""

from dataclasses import dataclass
from typing import Any

import structlog

from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, WhatsAppBotClient
from products.slack_app.backend.slack_thread import _format_task_error

logger = structlog.get_logger(__name__)

# WhatsApp reactions accept any single emoji; map the reaction names the tasks
# product uses. Unknown names are skipped.
_REACTION_EMOJI = {
    "eyes": "👀",
    "hedgehog": "🎉",
}

_ERROR_TRUNCATION_LIMIT = 200


@dataclass
class WhatsAppThreadContext:
    """Context for posting replies into the WhatsApp DM that spawned a task."""

    integration_id: int
    wa_id: str
    root_message_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            # The dispatch key thread_handler_from_context routes on — load-bearing.
            "provider": "whatsapp",
            "integration_id": self.integration_id,
            "wa_id": self.wa_id,
            "root_message_id": self.root_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WhatsAppThreadContext":
        return cls(
            integration_id=data["integration_id"],
            wa_id=data["wa_id"],
            root_message_id=data["root_message_id"],
        )


class WhatsAppThreadHandler:
    """Terminal-updates-only ``ChatThreadHandler`` implementation for WhatsApp."""

    def __init__(self, context: WhatsAppThreadContext) -> None:
        self.context = context
        self._client: WhatsAppBotClient | None = None

    def _get_client(self) -> WhatsAppBotClient:
        if self._client is None:
            self._client = WhatsAppBotClient()
        return self._client

    def _send(self, text: str) -> None:
        # Warn-and-continue on failure, matching the other handlers: a missed chat
        # update must never fail the task run itself.
        try:
            self._get_client().send_message(
                to=self.context.wa_id,
                text=text,
                reply_to_message_id=self.context.root_message_id,
            )
        except WhatsAppApiError as e:
            if e.is_window_closed:
                # The 24-hour customer service window closed before this update; a
                # template-message fallback is the known follow-up for this log key.
                logger.info("slack_app_whatsapp_window_closed", wa_id=self.context.wa_id)
            else:
                logger.warning("slack_app_whatsapp_thread_post_failed", error=str(e), wa_id=self.context.wa_id)

    def update_reaction(self, emoji: str) -> None:
        mapped = _REACTION_EMOJI.get(emoji)
        if mapped is None:
            return
        try:
            self._get_client().send_reaction(
                to=self.context.wa_id,
                message_id=self.context.root_message_id,
                emoji=mapped,
            )
        except WhatsAppApiError as e:
            logger.warning("slack_app_whatsapp_reaction_failed", error=str(e), wa_id=self.context.wa_id)

    # --- Terminal updates ---

    def post_pr_opened(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = None,
    ) -> None:
        # reply_target_slack_user_id exists for protocol compatibility; a WhatsApp DM
        # has exactly one human in it.
        text = f"Pull request opened: {pr_url}"
        if task_url:
            text += f"\nTrack it in PostHog: {task_url}"
        self._send(text)

    def post_completion(self, task_url: str | None) -> None:
        text = "Task completed."
        if task_url:
            text += f"\nDetails in PostHog: {task_url}"
        self._send(text)

    def post_error(self, error: str, task_url: str | None, recovery_hint: str | None = None) -> None:
        # recovery_hint carries Slack-specific copy that WhatsApp v1 can't honor,
        # so it's ignored in favor of our own line.
        formatted = _format_task_error(error)
        if len(formatted) > _ERROR_TRUNCATION_LIMIT:
            formatted = formatted[:_ERROR_TRUNCATION_LIMIT]
        text = f"Task failed: {formatted}"
        if task_url:
            text += f"\nDetails in PostHog: {task_url}"
        text += "\nMessage me again with more detail to retry."
        self._send(text)

    def post_cancelled(self, task_url: str | None, recovery_hint: str | None = None) -> None:
        text = "Stopped this run."
        if task_url:
            text += f"\nDetails in PostHog: {task_url}"
        text += "\nMessage me again when you want to pick it back up."
        self._send(text)

    def post_thread_message(self, text: str) -> None:
        self._send(text)

    def post_note(self, text: str) -> None:
        self._send(text)

    # --- No-ops: WhatsApp has no streaming or progress-message choreography ---

    def start_status_stream(
        self,
        first_task_id: str | None = None,
        first_task_title: str | None = None,
        first_task_details: str | None = None,
        first_markdown_text: str | None = None,
    ) -> str | None:
        return None

    def append_status_chunks(
        self,
        ts: str,
        task_updates: list[dict[str, Any]] | None = None,
        markdown_text: str | None = None,
    ) -> None:
        return None

    def stop_status_stream(
        self,
        ts: str,
        complete_task_id: str | None = None,
        complete_task_title: str | None = None,
        complete_task_details: str | None = None,
        final_markdown: str | None = None,
    ) -> None:
        return None

    def post_or_update_progress(
        self,
        stage: str,
        task_url: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        return None

    def delete_progress(self) -> None:
        return None
