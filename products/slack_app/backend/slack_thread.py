from dataclasses import dataclass
from typing import Any

import structlog
from slack_sdk import WebClient

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

PROGRESS_MESSAGE_MARKER = "Working on task..."


@dataclass
class SlackThreadContext:
    """Context for posting messages to a Slack thread."""

    integration_id: int
    channel: str
    thread_ts: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "integration_id": self.integration_id,
            "channel": self.channel,
            "thread_ts": self.thread_ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlackThreadContext":
        return cls(
            integration_id=data["integration_id"],
            channel=data["channel"],
            thread_ts=data["thread_ts"],
        )


class SlackThreadHandler:
    """Handler for posting updates to a Slack thread during task execution."""

    def __init__(self, context: SlackThreadContext):
        self.context = context
        self._integration: Integration | None = None
        self._client: WebClient | None = None
        self._bot_user_id: str | None = None

    def _get_integration(self) -> Integration:
        if self._integration is None:
            self._integration = Integration.objects.get(id=self.context.integration_id)
        return self._integration

    def _get_client(self):
        if self._client is None:
            integration = self._get_integration()
            self._client = SlackIntegration(integration).client
        return self._client

    def _get_bot_user_id(self) -> str | None:
        if self._bot_user_id is None:
            try:
                response = self._get_client().auth_test()
                self._bot_user_id = response.get("user_id")
            except Exception as e:
                logger.warning("slack_auth_test_failed", error=str(e))
        return self._bot_user_id

    def _find_progress_message_ts(self) -> str | None:
        """Find existing progress message in the thread."""
        try:
            client = self._get_client()
            bot_user_id = self._get_bot_user_id()
            if not bot_user_id:
                return None

            response = client.conversations_replies(
                channel=self.context.channel,
                ts=self.context.thread_ts,
                limit=50,
            )
            messages = response.get("messages", [])

            for msg in messages:
                if msg.get("user") == bot_user_id and PROGRESS_MESSAGE_MARKER in msg.get("text", ""):
                    return msg.get("ts")
        except Exception as e:
            logger.warning("slack_find_progress_message_failed", error=str(e))
        return None

    def post_or_update_progress(self, stage: str, task_url: str | None = None) -> None:
        """Post a new progress message or update the existing one."""
        text = f"*{PROGRESS_MESSAGE_MARKER}* :hourglass_flowing_sand:\nStage: {stage}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]

        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View agent logs", "emoji": True},
                            "url": task_url,
                        },
                    ],
                }
            )

        try:
            client = self._get_client()
            progress_ts = self._find_progress_message_ts()

            if progress_ts:
                client.chat_update(
                    channel=self.context.channel,
                    ts=progress_ts,
                    text=text,
                    blocks=blocks,
                )
            else:
                client.chat_postMessage(
                    channel=self.context.channel,
                    thread_ts=self.context.thread_ts,
                    text=text,
                    blocks=blocks,
                )
        except Exception as e:
            logger.exception("slack_progress_update_failed", error=str(e))

    def post_completion(self, pr_url: str | None, task_url: str) -> None:
        """Post completion message with PR link."""
        if pr_url:
            header = "*Pull Request Created* :rocket:"
        else:
            header = "*Task Completed* :white_check_mark:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]

        buttons: list[dict[str, Any]] = []
        if pr_url:
            buttons.append(
                {"type": "button", "text": {"type": "plain_text", "text": "View PR", "emoji": True}, "url": pr_url}
            )
        buttons.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open in PostHog", "emoji": True},
                "url": task_url,
            }
        )

        blocks.append({"type": "actions", "elements": buttons})

        self._delete_progress_and_post(header, blocks)

    def post_error(self, error: str, task_url: str) -> None:
        """Post error message with link to PostHog for details."""
        header = "*Task Failed* :x:"
        truncated_error = error[:200] if len(error) > 200 else error

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": truncated_error}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "See details in PostHog", "emoji": True},
                        "url": task_url,
                    },
                ],
            },
        ]

        self._delete_progress_and_post(f"{header}\n{truncated_error}", blocks)

    def _delete_progress_and_post(self, text: str, blocks: list[dict[str, Any]]) -> None:
        """Delete progress message if exists and post final message."""
        try:
            client = self._get_client()
            progress_ts = self._find_progress_message_ts()

            if progress_ts:
                try:
                    client.chat_delete(channel=self.context.channel, ts=progress_ts)
                except Exception as e:
                    logger.warning("slack_delete_progress_failed", error=str(e))

            client.chat_postMessage(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                text=text,
                blocks=blocks,
            )
        except Exception as e:
            logger.exception("slack_completion_post_failed", error=str(e))
