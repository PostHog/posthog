"""Telegram conversation context and thread handler.

Mirrors ``slack_thread.py`` for the Telegram surface, deliberately smaller: Telegram
chats get the initial ack, relayed agent messages, and the terminal outcome — nothing
in between. Progress and status-stream methods are no-ops because Telegram has no
message streaming and edit-choreography would add API surface without adding signal.
"""

from dataclasses import dataclass
from typing import Any

import structlog

from products.slack_app.backend.services.telegram_api import TelegramApiError, TelegramBotClient
from products.slack_app.backend.slack_thread import _format_task_error

logger = structlog.get_logger(__name__)

# Telegram's setMessageReaction accepts a fixed emoji list; map the reaction names the
# tasks product uses onto members of that list. Unknown names are skipped.
_REACTION_EMOJI = {
    "eyes": "👀",
    "hedgehog": "🎉",
}

_ERROR_TRUNCATION_LIMIT = 200


@dataclass
class TelegramThreadContext:
    """Context for posting replies into the Telegram chat that spawned a task."""

    integration_id: int
    chat_id: str
    root_message_id: str
    telegram_user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            # The dispatch key thread_handler_from_context routes on — load-bearing.
            "provider": "telegram",
            "integration_id": self.integration_id,
            "chat_id": self.chat_id,
            "root_message_id": self.root_message_id,
        }
        if self.telegram_user_id is not None:
            d["telegram_user_id"] = self.telegram_user_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TelegramThreadContext":
        return cls(
            integration_id=data["integration_id"],
            chat_id=data["chat_id"],
            root_message_id=data["root_message_id"],
            telegram_user_id=data.get("telegram_user_id"),
        )


class TelegramThreadHandler:
    """Terminal-updates-only ``ChatThreadHandler`` implementation for Telegram."""

    def __init__(self, context: TelegramThreadContext) -> None:
        self.context = context
        self._client: TelegramBotClient | None = None

    def _get_client(self) -> TelegramBotClient:
        if self._client is None:
            self._client = TelegramBotClient()
        return self._client

    def _send(self, text: str) -> None:
        # Warn-and-continue on failure, matching SlackThreadHandler: a missed chat
        # update must never fail the task run itself.
        try:
            self._get_client().send_message(
                chat_id=self.context.chat_id,
                text=text,
                reply_to_message_id=self.context.root_message_id,
            )
        except TelegramApiError as e:
            logger.warning("slack_app_telegram_thread_post_failed", error=str(e), chat_id=self.context.chat_id)

    def update_reaction(self, emoji: str) -> None:
        mapped = _REACTION_EMOJI.get(emoji)
        if mapped is None:
            return
        try:
            self._get_client().set_message_reaction(
                chat_id=self.context.chat_id,
                message_id=self.context.root_message_id,
                emoji=mapped,
            )
        except TelegramApiError as e:
            logger.warning("slack_app_telegram_reaction_failed", error=str(e), chat_id=self.context.chat_id)

    # --- Terminal updates ---

    def post_pr_opened(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = None,
    ) -> None:
        # reply_target_slack_user_id exists for protocol compatibility; Telegram replies
        # already notify the root message's author.
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
        # recovery_hint carries Slack-specific copy ("reply in this thread with retry")
        # that Telegram v1 can't honor, so it's ignored in favor of our own line.
        formatted = _format_task_error(error)
        if len(formatted) > _ERROR_TRUNCATION_LIMIT:
            formatted = formatted[:_ERROR_TRUNCATION_LIMIT]
        text = f"Task failed: {formatted}"
        if task_url:
            text += f"\nDetails in PostHog: {task_url}"
        text += "\nMention me again with more detail to retry."
        self._send(text)

    def post_cancelled(self, task_url: str | None, recovery_hint: str | None = None) -> None:
        text = "Stopped this run."
        if task_url:
            text += f"\nDetails in PostHog: {task_url}"
        text += "\nMention me again when you want to pick it back up."
        self._send(text)

    def post_thread_message(self, text: str) -> None:
        self._send(text)

    def post_note(self, text: str) -> None:
        self._send(text)

    # --- No-ops: Telegram has no streaming or progress-message choreography ---

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

    def post_or_update_progress(self, stage: str, task_url: str | None = None) -> None:
        return None

    def delete_progress(self) -> None:
        return None
