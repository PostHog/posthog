import re
from dataclasses import dataclass
from typing import Any

import structlog
from slack_sdk import WebClient

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

PROGRESS_MESSAGE_MARKER = "Working on task..."
UPSTREAM_PROVIDER_FAILURE_MESSAGE = (
    "The upstream AI provider failed to process the request. Please retry the task in a few minutes."
)
UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN = re.compile(r"\bapi error:\s*(?:429|5\d\d)\b", re.IGNORECASE)
DEFAULT_FAILURE_RECOVERY_HINT = (
    "Reply in this thread with `retry` to try again from the latest checkpoint, "
    "or add the missing details and I'll re-plan before continuing."
)
DEFAULT_CANCELLED_RECOVERY_HINT = (
    "Reply in this thread when you want to resume, and include any new direction I should follow."
)


_TASK_FIELD_LIMIT = 256
_MARKDOWN_CHUNK_LIMIT = 12000


def _split_markdown_text(text: str, limit: int = _MARKDOWN_CHUNK_LIMIT) -> list[str]:
    """≤limit pieces at paragraph/line boundaries. Slack stitches chunks server-side."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        pieces.append(remaining)
    return pieces


def _task_update_chunk(
    task_id: str,
    title: str,
    status: str,
    details: str | None,
) -> dict[str, Any]:
    """task_update chunk with title/details truncated to Slack's 256-char cap."""
    chunk: dict[str, Any] = {
        "type": "task_update",
        "id": task_id,
        "title": title[:_TASK_FIELD_LIMIT],
        "status": status,
    }
    if details:
        chunk["details"] = details[:_TASK_FIELD_LIMIT]
    return chunk


def _format_task_error(error: str) -> str:
    error = error.strip()
    if not error:
        return "Unknown error"

    if UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN.search(error):
        return UPSTREAM_PROVIDER_FAILURE_MESSAGE

    return error


@dataclass
class SlackThreadContext:
    """Context for posting messages to a Slack thread."""

    integration_id: int
    channel: str
    thread_ts: str
    user_message_ts: str | None = None
    mentioning_slack_user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "integration_id": self.integration_id,
            "channel": self.channel,
            "thread_ts": self.thread_ts,
        }
        if self.user_message_ts is not None:
            d["user_message_ts"] = self.user_message_ts
        if self.mentioning_slack_user_id is not None:
            d["mentioning_slack_user_id"] = self.mentioning_slack_user_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlackThreadContext":
        return cls(
            integration_id=data["integration_id"],
            channel=data["channel"],
            thread_ts=data["thread_ts"],
            user_message_ts=data.get("user_message_ts"),
            mentioning_slack_user_id=data.get("mentioning_slack_user_id"),
        )


class SlackThreadHandler:
    """Handler for posting updates to a Slack thread during task execution."""

    def __init__(self, context: SlackThreadContext) -> None:
        self.context = context
        self._integration: Integration | None = None
        self._client: WebClient | None = None
        self._bot_user_id: str | None = None

    def _get_integration(self) -> Integration:
        if self._integration is None:
            # nosemgrep: idor-lookup-without-team (internal context, ID from Slack event mapping)
            self._integration = Integration.objects.get(id=self.context.integration_id)
        return self._integration

    def _get_client(self) -> WebClient:
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
            messages: list[dict[str, Any]] = response.get("messages", [])

            for msg in messages:
                if msg.get("user") == bot_user_id and PROGRESS_MESSAGE_MARKER in msg.get("text", ""):
                    return msg.get("ts")
        except Exception as e:
            logger.warning("slack_find_progress_message_failed", error=str(e))
        return None

    def update_reaction(self, emoji: str) -> None:
        """Swap the reaction on the user's mention message."""
        target_ts = self.context.user_message_ts or self.context.thread_ts
        try:
            client = self._get_client()
            try:
                client.reactions_remove(channel=self.context.channel, timestamp=target_ts, name="eyes")
            except Exception:
                pass
            client.reactions_add(
                channel=self.context.channel,
                timestamp=target_ts,
                name=emoji,
            )
        except Exception as e:
            logger.warning("slack_update_reaction_failed", error=str(e))

    def start_status_stream(
        self,
        first_task_id: str | None = None,
        first_task_title: str | None = None,
        first_task_details: str | None = None,
        first_markdown_text: str | None = None,
    ) -> str | None:
        """chat.startStream in plan-block mode. Seed with EITHER a task_update
        (starts with a plan-block step) OR a markdown_text chunk (starts as
        prose; a plan block appears later when a task_update arrives)."""
        if not self.context.mentioning_slack_user_id:
            return None
        chunks: list[dict[str, Any]] = []
        if first_task_id and first_task_title:
            chunks.append(_task_update_chunk(first_task_id, first_task_title, "in_progress", first_task_details))
        if first_markdown_text:
            for piece in _split_markdown_text(first_markdown_text):
                chunks.append({"type": "markdown_text", "text": piece})
        if not chunks:
            return None
        try:
            client = self._get_client()
            integration = self._get_integration()
            response = client.chat_startStream(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                recipient_user_id=self.context.mentioning_slack_user_id,
                recipient_team_id=integration.integration_id,
                task_display_mode="plan",
                chunks=chunks,
            )
            ts = response.get("ts") if isinstance(response, dict) else response["ts"]
            return ts if isinstance(ts, str) else None
        except Exception as e:
            logger.warning("slack_app_status_stream_start_failed", error=str(e))
            return None

    def append_status_chunks(
        self,
        ts: str,
        task_updates: list[dict[str, Any]] | None = None,
        markdown_text: str | None = None,
    ) -> None:
        """Append plan-block step transitions and/or markdown_text chunks."""
        chunks: list[dict[str, Any]] = []
        for t in task_updates or []:
            task_id = t.get("id")
            title = t.get("title")
            status = t.get("status")
            if not task_id or not title or not status:
                continue
            chunks.append(_task_update_chunk(str(task_id), str(title), str(status), t.get("details")))
        if markdown_text:
            for piece in _split_markdown_text(markdown_text):
                chunks.append({"type": "markdown_text", "text": piece})
        if not chunks:
            return
        try:
            self._get_client().chat_appendStream(
                channel=self.context.channel,
                ts=ts,
                chunks=chunks,
            )
        except Exception as e:
            logger.warning("slack_app_status_stream_append_failed", error=str(e))

    def stop_status_stream(
        self,
        ts: str,
        complete_task_id: str | None = None,
        complete_task_title: str | None = None,
        complete_task_details: str | None = None,
        final_markdown: str | None = None,
    ) -> None:
        """Final flush: mark the last plan-block step complete, stream the final
        answer as markdown_text chunks (this is what STAYS in the message body),
        append a trailing @-mention for one notification, then chat.stopStream."""
        final_chunks: list[dict[str, Any]] = []
        if complete_task_id and complete_task_title:
            final_chunks.append(
                _task_update_chunk(complete_task_id, complete_task_title, "complete", complete_task_details)
            )
        if final_markdown:
            for piece in _split_markdown_text(final_markdown):
                final_chunks.append({"type": "markdown_text", "text": piece})
        if self.context.mentioning_slack_user_id:
            # Newlines keep the mention off the tail of the last streamed prose chunk.
            final_chunks.append({"type": "markdown_text", "text": f"\n\n<@{self.context.mentioning_slack_user_id}>"})
        if final_chunks:
            try:
                self._get_client().chat_appendStream(
                    channel=self.context.channel,
                    ts=ts,
                    chunks=final_chunks,
                )
            except Exception as e:
                logger.warning("slack_app_status_stream_final_append_failed", error=str(e))
        try:
            self._get_client().chat_stopStream(
                channel=self.context.channel,
                ts=ts,
            )
        except Exception as e:
            logger.warning("slack_app_status_stream_stop_failed", error=str(e))

    def post_or_update_progress(
        self,
        stage: str,
        task_url: str | None = None,
    ) -> None:
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
                            "text": {
                                "type": "plain_text",
                                "text": "View agent logs",
                                "emoji": True,
                            },
                            "url": task_url,
                        }
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

    def post_pr_opened(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = None,
    ) -> None:
        """Post the single per-run "PR opened" card.

        Used at every lifecycle moment a run surfaces a PR for the first
        time — mid-run announcement, post-sandbox cleanup, terminal
        completion. The activity-level dedupe in
        ``_post_pr_opened_notification_once`` ensures this fires once per
        ``pr_url`` per run regardless of which moment got there first.

        ``reply_target_slack_user_id`` is the resolved actor — typically the
        most recent thread participant. ``None`` produces an untagged message.
        """
        mention_prefix = f"<@{reply_target_slack_user_id}> " if reply_target_slack_user_id else ""
        header = f"{mention_prefix}*Pull request opened* :rocket:"

        buttons: list[dict[str, Any]] = [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View PR",
                    "emoji": True,
                },
                "url": pr_url,
            },
        ]
        if task_url:
            buttons.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Open in PostHog",
                        "emoji": True,
                    },
                    "url": task_url,
                }
            )

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "actions", "elements": buttons},
        ]

        self._delete_progress_and_post(header, blocks)

    def post_thread_message(self, text: str) -> None:
        """Post a plain message in the existing thread."""
        try:
            self._get_client().chat_postMessage(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                text=text,
            )
        except Exception as e:
            logger.warning("slack_post_thread_message_failed", error=str(e))

    def post_completion(self, task_url: str | None) -> None:
        """Post the no-PR completion message.

        Runs that produce a PR surface it via ``post_pr_opened`` (routed
        through ``_post_pr_opened_notification_once`` for once-per-URL
        semantics). This card is the "task finished without opening a PR"
        terminal state.
        """
        header = "*Task Completed* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]
        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Open in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        }
                    ],
                }
            )

        self._delete_progress_and_post(header, blocks)

    def post_error(
        self, error: str, task_url: str | None, recovery_hint: str | None = DEFAULT_FAILURE_RECOVERY_HINT
    ) -> None:
        """Post error message with link to PostHog for details."""
        header = "*Task Failed* :x:"
        error = _format_task_error(error)
        truncated_error = error[:200] if len(error) > 200 else error

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": truncated_error}},
        ]
        if recovery_hint:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": recovery_hint}})
        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "See details in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        },
                    ],
                }
            )

        self._delete_progress_and_post(f"{header}\n{truncated_error}", blocks)

    def post_cancelled(self, task_url: str | None, recovery_hint: str | None = DEFAULT_CANCELLED_RECOVERY_HINT) -> None:
        """Post cancelled message with link to PostHog for details."""
        header = "*Sandbox stopped* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]
        if recovery_hint:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": recovery_hint}})
        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Open in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        },
                    ],
                }
            )

        self._delete_progress_and_post(header, blocks)

    def delete_progress(self) -> None:
        """Delete the progress message if it exists."""
        try:
            client = self._get_client()
            progress_ts = self._find_progress_message_ts()
            if progress_ts:
                client.chat_delete(channel=self.context.channel, ts=progress_ts)
        except Exception as e:
            logger.warning("slack_delete_progress_failed", error=str(e))

    def _delete_progress_and_post(self, text: str, blocks: list[dict[str, Any]]) -> None:
        """Delete progress message if exists and post final message."""
        try:
            self.delete_progress()
            self._get_client().chat_postMessage(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                text=text,
                blocks=blocks,
            )
        except Exception as e:
            logger.exception("slack_completion_post_failed", error=str(e))
