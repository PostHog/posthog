import re
import hashlib
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

# Legacy fixed ack emoji. Tasks ack'd before the deterministic pool landed used
# `:seedling:` exclusively; cleanup still tries to remove it so in-flight tasks
# at deploy time don't end up with a stale reaction. Can be dropped a release
# cycle after this lands.
_LEGACY_ACK_EMOJI = "seedling"

# Pool of fun, universally-available Slack emoji names used to acknowledge a mention
# before the bot starts the longer-running work. Anything in this pool is treated as
# an in-progress signal by `update_reaction` / `_set_followup_done_reaction` and is
# cleaned up when the bot reaches a terminal state. Keep these distinct from the
# stage-specific reactions (:mag: for searching, :hedgehog: for done, :x: for failed)
# and from "eyes" (the follow-up ack), so the cleanup pool stays unambiguous.
RANDOM_ACK_EMOJIS: tuple[str, ...] = (
    # Friendly greetings & thinking
    "seedling",
    "wave",
    "robot_face",
    "thinking_face",
    "nerd_face",
    "sunglasses",
    # Energy & magic
    "sparkles",
    "rocket",
    "zap",
    "crystal_ball",
    "mage",
    "star2",
    "dizzy",
    "rainbow",
    # Working / tinkering
    "hammer_and_wrench",
    "gear",
    "coffee",
    "keyboard",
    "telescope",
    "brain",
    "bulb",
    "compass",
    # Nature & luck
    "four_leaf_clover",
    "cherry_blossom",
    "sunflower",
    "herb",
    # Animal companions
    "owl",
    "otter",
    "penguin",
    "fox_face",
    "bee",
    "butterfly",
    "unicorn_face",
    "turtle",
    "panda_face",
    "koala",
    "hamster",
    # Play & whimsy
    "art",
    "balloon",
    "game_die",
    # Characters
    "ninja",
    "alien",
    "space_invader",
)


def ack_emoji_for(message_ts: str) -> str:
    """Pick an emoji from the ack pool deterministically per Slack message ts.

    `create_posthog_code_task_for_repo_activity` retries up to 3 times. With a
    truly random pick, each retry could choose a different emoji and bypass
    `_safe_react`'s `already_reacted` short-circuit, piling extra reactions on
    the user's mention. Keying the choice on the message ts keeps every replay
    landing on the same emoji. `hashlib` (not `hash()`) is used so the choice
    is stable across worker processes — PYTHONHASHSEED randomization would
    otherwise diverge per replay.
    """
    digest = hashlib.sha256(message_ts.encode("utf-8")).digest()
    return RANDOM_ACK_EMOJIS[int.from_bytes(digest[:4], "big") % len(RANDOM_ACK_EMOJIS)]


def stale_ack_emojis_for(message_ts: str) -> tuple[str, ...]:
    """Reactions a cleanup pass should try to remove from `message_ts`.

    `eyes` is the follow-up ack, the deterministic pool pick is the initial
    ack, and `_LEGACY_ACK_EMOJI` covers tasks ack'd before this pool landed.
    Keeping the set small (vs. iterating the full pool) avoids burning the
    `reactions.remove` rate limit on guaranteed-`no_reaction` calls.
    """
    return ("eyes", ack_emoji_for(message_ts), _LEGACY_ACK_EMOJI)


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
            for stale in stale_ack_emojis_for(target_ts):
                try:
                    client.reactions_remove(channel=self.context.channel, timestamp=target_ts, name=stale)
                except Exception:
                    pass
            client.reactions_add(
                channel=self.context.channel,
                timestamp=target_ts,
                name=emoji,
            )
        except Exception as e:
            logger.warning("slack_update_reaction_failed", error=str(e))

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

    def post_pr_opened_sandbox_cleaned(self, pr_url: str, task_url: str) -> None:
        """Post final PR message after sandbox cleanup."""
        header = "*Pull request opened* :rocket:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View PR",
                            "emoji": True,
                        },
                        "url": pr_url,
                    },
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
            },
        ]

        self._delete_progress_and_post(header, blocks)

    def post_pr_opened(self, pr_url: str, task_url: str) -> None:
        """Post PR opened message with action buttons."""
        mention_prefix = f"<@{self.context.mentioning_slack_user_id}> " if self.context.mentioning_slack_user_id else ""
        header = f"{mention_prefix}Pull request opened."

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View PR",
                            "emoji": True,
                        },
                        "url": pr_url,
                    },
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
            },
        ]

        try:
            self._get_client().chat_postMessage(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                text=header,
                blocks=blocks,
            )
        except Exception as e:
            logger.warning("slack_post_pr_opened_failed", error=str(e))

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

    def post_completion(self, pr_url: str | None, task_url: str) -> None:
        """Post completion message with PR link."""
        if pr_url:
            header = "*Pull Request Created* :rocket:"
        else:
            header = "*Task Completed* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]

        buttons: list[dict[str, Any]] = []
        if pr_url:
            buttons.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View PR", "emoji": True},
                    "url": pr_url,
                }
            )
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

        blocks.append({"type": "actions", "elements": buttons})

        self._delete_progress_and_post(header, blocks)

    def post_error(self, error: str, task_url: str) -> None:
        """Post error message with link to PostHog for details."""
        header = "*Task Failed* :x:"
        error = _format_task_error(error)
        truncated_error = error[:200] if len(error) > 200 else error

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": truncated_error}},
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
            },
        ]

        self._delete_progress_and_post(f"{header}\n{truncated_error}", blocks)

    def post_cancelled(self, task_url: str) -> None:
        """Post cancelled message with link to PostHog for details."""
        header = "*Sandbox stopped* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
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
            },
        ]

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
