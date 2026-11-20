"""Finds the threads that moved in the channels a person and the bot share, for the daily work focus.

The bot reads each channel's root messages once a day for the whole workspace and has Jev score each root. Only ids,
counts and scores wait in the cache for the other people in the workspace; no message content is stored. A person's
run keeps the threads they are in, adds the best-scored others from their channels, and reads those few threads in
full right before the writer sees them.
"""

import re
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError, SlackClientError

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import NoulAnswer, NoulQuestion
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, build_system_one_client
from posthog.models.integration import SlackIntegration
from posthog.token_bucket import BucketDecision, Budget, consume

from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# The bot lists and reads channels, so these are bot scopes. Private channels need the second pair as well.
CHANNEL_SCOPES = frozenset({"channels:read", "channels:history"})
PRIVATE_CHANNEL_SCOPES = frozenset({"groups:read", "groups:history"})

# A thread that started earlier and moved overnight is news too, so the index reaches back further than one day.
# A busy channel keeps its newest roots; the rest fall off.
INDEX_LOOKBACK = timedelta(days=3)
CHANNELS_PER_WORKSPACE = 100
ROOTS_PER_CHANNEL = 50
INDEX_TTL_SECONDS = 36 * 3600
# The channel reads are tier 3 calls, about 50 a minute, shared by every person's run in the workspace.
HISTORY_BUDGET = Budget(burst=60, per_hour=1200)

ROOT_CHARS = 300
THREADS_PER_PERSON = 5
THREAD_TAIL_REPLIES = 6
REPLY_CHARS = 300
THREAD_CHARS = 2000

RANK_MODEL = DEFAULT_DECISION_MODEL
RANK_TIMEOUT_SECONDS = 20.0
RANK_MIN_PROBABILITY = 0.5
RANK_INSTRUCTIONS = (
    "`roots` holds the first messages of Slack threads from a team's channels, with the number of replies each got. "
    "For the message this question names, decide whether a teammate who missed the day would want to know about it."
)
RANK_TRUE = "It reports a decision, an incident, a launch, a blocker, or asks the team for input."
RANK_FALSE = "It is chat, a greeting, a status note, an automated post, or a question one person already answered."

_MENTION = re.compile(r"<@(U[A-Z0-9]+)")


class DailySummaryRateLimited(Exception):
    """Raised before anything is read, so the run can retry later."""


@frozen
class RootRef:
    channel_id: str
    ts: str
    author: str | None
    reply_count: int
    latest_reply: float
    reply_users: tuple[str, ...]
    mentions: tuple[str, ...]
    # Jev's probability that a teammate who missed the day wants to know. Zero when it was never scored.
    score: float = 0.0

    @property
    def posted_at(self) -> float:
        return float(self.ts)

    @property
    def moved_at(self) -> float:
        return max(self.posted_at, self.latest_reply)


@frozen
class SummaryThread:
    channel_id: str
    ts: str
    text: str
    # The person is in the thread: they started it, replied, or were mentioned.
    involves_person: bool
    permalink: str | None = None


def summary_threads(integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime) -> list[SummaryThread]:
    """The threads to summarise for this person, each read in full, most relevant first. Empty when the bot cannot
    read channels or nothing moved."""
    slack = SlackIntegration(integration)
    if slack.missing_scopes(CHANNEL_SCOPES):
        return []
    private = not slack.missing_scopes(PRIVATE_CHANNEL_SCOPES)
    index = _workspace_index(integration, slack, private=private)
    if not index:
        return []
    channels = _person_channels(slack, slack_user_id, private=private)
    kept = pick_threads(index, slack_user_id, channels, since=since)
    return [thread for root in kept if (thread := _read_thread(slack, root, slack_user_id)) is not None]


def pick_threads(roots: list[RootRef], slack_user_id: str, channels: set[str], *, since: datetime) -> list[RootRef]:
    """The person's own threads that moved come first, newest first. The rest of their channels fill the remaining
    places by Jev's score."""
    since_at = since.timestamp()
    moved = [root for root in roots if root.channel_id in channels and root.moved_at >= since_at]
    own = [
        root
        for root in moved
        if (root.author == slack_user_id and root.reply_count > 0 and root.latest_reply >= since_at)
        or slack_user_id in root.reply_users
        or slack_user_id in root.mentions
    ]
    own.sort(key=lambda root: root.moved_at, reverse=True)
    others = [
        root
        for root in moved
        if root not in own and root.author != slack_user_id and root.score >= RANK_MIN_PROBABILITY
    ]
    others.sort(key=lambda root: (root.score, root.moved_at), reverse=True)
    return (own + others)[:THREADS_PER_PERSON]


def _workspace_index(integration: WorkspaceIntegration, slack: SlackIntegration, *, private: bool) -> list[RootRef]:
    """The scored roots of every channel the bot is in, built once a day for the workspace and shared by every
    person's run. Holds ids, counts and scores, never text."""
    key = f"slack_app:daily_summary:index:{integration.integration_id}:{timezone.now().date().isoformat()}"
    cached = cache.get(key)
    if isinstance(cached, list):
        return [RootRef(**item) for item in cached]
    channels = _bot_channels(slack, private=private)
    decision = consume(
        f"slack_app:daily_summary:history:{integration.integration_id}", HISTORY_BUDGET, cost=len(channels)
    )
    if isinstance(decision, BucketDecision) and not decision.allowed:
        raise DailySummaryRateLimited
    oldest = (timezone.now() - INDEX_LOOKBACK).timestamp()
    roots: list[RootRef] = []
    texts: list[str] = []
    for channel_id in channels:
        for message in _channel_roots(slack, channel_id, oldest=oldest):
            roots.append(_root_ref(channel_id, message))
            texts.append(str(message.get("text") or "")[:ROOT_CHARS])
    roots = _scored(integration, roots, texts)
    cache.set(key, [asdict(root) for root in roots], INDEX_TTL_SECONDS)
    return roots


def _bot_channels(slack: SlackIntegration, *, private: bool) -> list[str]:
    types = "public_channel,private_channel" if private else "public_channel"
    channels: list[str] = []
    cursor = ""
    try:
        while len(channels) < CHANNELS_PER_WORKSPACE:
            response = slack.client.conversations_list(
                types=types, exclude_archived=True, limit=200, cursor=cursor or None
            )
            channels.extend(
                str(channel["id"]) for channel in response.get("channels") or [] if channel.get("is_member")
            )
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_channels_failed", exc_info=True)
    return channels[:CHANNELS_PER_WORKSPACE]


def _channel_roots(slack: SlackIntegration, channel_id: str, *, oldest: float) -> list[dict[str, Any]]:
    try:
        response = slack.client.conversations_history(channel=channel_id, oldest=str(oldest), limit=ROOTS_PER_CHANNEL)
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_history_failed", channel=channel_id, exc_info=True)
        return []
    return [
        message
        for message in response.get("messages") or []
        if not message.get("subtype") and not message.get("bot_id") and str(message.get("text") or "").strip()
    ]


def _root_ref(channel_id: str, message: dict[str, Any]) -> RootRef:
    text = str(message.get("text") or "")
    return RootRef(
        channel_id=channel_id,
        ts=str(message["ts"]),
        author=str(message["user"]) if message.get("user") else None,
        reply_count=int(message.get("reply_count") or 0),
        latest_reply=float(message.get("latest_reply") or 0),
        reply_users=tuple(str(user) for user in message.get("reply_users") or []),
        mentions=tuple(dict.fromkeys(_MENTION.findall(text))),
    )


def _scored(integration: WorkspaceIntegration, roots: list[RootRef], texts: list[str]) -> list[RootRef]:
    if not roots:
        return []
    client = build_system_one_client(
        model=RANK_MODEL,
        ai_product="slack_app",
        team_id=integration.team_id,
        properties={"slack_app_classifier": "daily_summary_rank", "slack_app_flow": "slack_app_daily_focus"},
        timeout=RANK_TIMEOUT_SECONDS,
        privacy_mode=True,
    )
    scores = [0.0] * len(roots)
    for start in range(0, len(roots), GATEWAY_MAX_QUESTIONS):
        batch = range(start, min(start + GATEWAY_MAX_QUESTIONS, len(roots)))
        keys = {f"r{index}": index for index in batch}
        result = client.decide(
            state={
                "roots": {
                    key: {"text": texts[index], "replies": roots[index].reply_count} for key, index in keys.items()
                }
            },
            questions={
                key: NoulQuestion(
                    instructions=f"{RANK_INSTRUCTIONS} This question names `roots.{key}`.",
                    criteria_true=RANK_TRUE,
                    criteria_false=RANK_FALSE,
                )
                for key in keys
            },
        )
        for key, index in keys.items():
            answer = result.answers.get(key)
            if isinstance(answer, NoulAnswer):
                scores[index] = answer.probability
    return [replace(root, score=score) for root, score in zip(roots, scores)]


def _person_channels(slack: SlackIntegration, slack_user_id: str, *, private: bool) -> set[str]:
    """The channels the person is in that the bot can see. A private channel shows only when the bot is in it too."""
    types = "public_channel,private_channel" if private else "public_channel"
    channels: set[str] = set()
    cursor = ""
    try:
        while True:
            response = slack.client.users_conversations(
                user=slack_user_id, types=types, exclude_archived=True, limit=200, cursor=cursor or None
            )
            channels.update(str(channel["id"]) for channel in response.get("channels") or [])
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_person_channels_failed", exc_info=True)
    return channels


def _read_thread(slack: SlackIntegration, root: RootRef, slack_user_id: str) -> SummaryThread | None:
    try:
        response = slack.client.conversations_replies(channel=root.channel_id, ts=root.ts, limit=100)
        permalink = slack.client.chat_getPermalink(channel=root.channel_id, message_ts=root.ts).get("permalink")
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_thread_failed", channel=root.channel_id, exc_info=True)
        return None
    messages = [m for m in response.get("messages") or [] if str(m.get("text") or "").strip() and not m.get("bot_id")]
    if not messages:
        return None
    involved = (
        root.author == slack_user_id
        or slack_user_id in root.reply_users
        or slack_user_id in root.mentions
        or any(m.get("user") == slack_user_id for m in messages)
    )
    return SummaryThread(
        channel_id=root.channel_id,
        ts=root.ts,
        text=thread_text(messages),
        involves_person=involved,
        permalink=permalink if isinstance(permalink, str) and permalink.startswith("https://") else None,
    )


def thread_text(messages: list[dict[str, Any]]) -> str:
    """The root and the last few replies, each as `<@user>: text`, within the writer's budget. The middle of a long
    thread is the part the writer needs least."""
    root, replies = messages[0], messages[1:]
    lines = [f"<@{root.get('user')}>: {str(root.get('text') or '')[:ROOT_CHARS]}"]
    skipped = max(len(replies) - THREAD_TAIL_REPLIES, 0)
    if skipped:
        lines.append(f"(+{skipped} earlier replies)")
    for reply in replies[-THREAD_TAIL_REPLIES:]:
        lines.append(f"<@{reply.get('user')}>: {str(reply.get('text') or '')[:REPLY_CHARS]}")
    return "\n".join(lines)[:THREAD_CHARS]
