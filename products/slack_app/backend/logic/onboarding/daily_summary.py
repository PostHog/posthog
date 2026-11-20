"""Finds the threads that moved in the channels a person and the bot share, for the daily work focus.

The sweep has the bot read each channel's root messages once a day for the whole workspace, before any person's run
starts, and has Jev score each root. Only ids, counts and scores wait in the cache for the people in the workspace;
no message content is stored. A person's run keeps the threads they are in, adds the best-scored others from their
channels, and reads those few threads in full right before the writer sees them.
"""

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Any, TypeVar

from django.core.cache import cache
from django.utils import timezone

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import NoulAnswer, NoulQuestion
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, build_system_one_client
from posthog.models.integration import SlackIntegration
from posthog.token_bucket import BucketDecision, Budget, consume

from products.slack_app.backend.feature_flags import is_slack_app_daily_summary_enabled
from products.slack_app.backend.services.slack_messages import mentions_slack_user, thread_permalink
from products.slack_app.backend.services.slack_user_oauth import linked_posthog_distinct_id
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
# Jev scores the newest roots across the workspace. Older ones stay in the index for the threads a person is in.
ROOTS_SCORED_PER_WORKSPACE = 400
INDEX_TTL_SECONDS = 36 * 3600
BUILD_LOCK_SECONDS = 300
# The index build reads one history page per channel, and Slack allows about 50 of those a minute per workspace.
# The burst covers one build of the largest index.
HISTORY_BUDGET = Budget(burst=CHANNELS_PER_WORKSPACE, per_hour=1200)
# A person in thousands of channels would page for minutes; the index's channels are found long before that.
MEMBER_PAGES = 5

ROOT_CHARS = 300
THREADS_PER_PERSON = 5
THREAD_TAIL_REPLIES = 6
REPLY_CHARS = 300
THREAD_CHARS = 2000
SUMMARY_REPLIES_LIMIT = 100
# Thread reads are tier 3 calls; a handful at once stays well inside the workspace's limit.
READ_WORKERS = 5

RANK_MODEL = DEFAULT_DECISION_MODEL
RANK_TIMEOUT_SECONDS = 20.0
RANK_MIN_PROBABILITY = 0.5
RANK_INSTRUCTIONS = (
    "`roots` holds the first messages of Slack threads from a team's channels, with the number of replies each got. "
    "For the message this question names, decide whether a teammate who missed the day would want to know about it."
)
RANK_TRUE = "It reports a decision, an incident, a launch, a blocker, or asks the team for input."
RANK_FALSE = (
    "It is chat, a greeting, a status note, an automated post, a request to PostHog's Slack app, or a question one "
    "person already answered."
)

_MENTION = re.compile(r"<@(U[A-Z0-9]+)")

_Item = TypeVar("_Item")
_Result = TypeVar("_Result")


class DailySummaryRateLimited(Exception):
    """Raised before anything is read, so the build can retry later."""


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
    def moved_at(self) -> float:
        return max(float(self.ts), self.latest_reply)

    def involves(self, user_id: str | None) -> bool:
        """The user started the thread, replied in it, or is mentioned in its root."""
        return bool(user_id) and (self.author == user_id or user_id in self.reply_users or user_id in self.mentions)


@frozen
class SummaryThread:
    channel_id: str
    ts: str
    text: str
    # The person is in the thread: they started it, replied, or were mentioned.
    involves_person: bool
    permalink: str | None = None


@frozen
class ReadThread:
    # The people's messages, root first, without bot posts and empty messages.
    messages: list[dict[str, Any]]
    # The app replied in the thread or was tagged in it, so the thread was a request to the app.
    app_took_part: bool


def wants_summary(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    return is_slack_app_daily_summary_enabled(
        integration, linked_posthog_distinct_id(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)
    )


def app_took_part(messages: Iterable[dict[str, Any]], bot_user_id: str | None) -> bool:
    if not bot_user_id:
        return False
    return any(
        message.get("user") == bot_user_id or mentions_slack_user(str(message.get("text") or ""), bot_user_id)
        for message in messages
    )


def read_thread(
    client: WebClient, channel_id: str, ts: str, *, bot_user_id: str | None, limit: int
) -> ReadThread | None:
    """One thread as the people wrote it. None when Slack will not return it."""
    try:
        response = client.conversations_replies(channel=channel_id, ts=ts, limit=limit)
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_thread_failed", channel=channel_id, exc_info=True)
        return None
    raw = response.get("messages") or []
    return ReadThread(
        messages=[m for m in raw if str(m.get("text") or "").strip() and not m.get("bot_id")],
        app_took_part=app_took_part(raw, bot_user_id),
    )


def parallel_map(fn: Callable[[_Item], _Result], items: list[_Item]) -> list[_Result]:
    """``fn`` over ``items`` a few at a time, in order. For Slack reads inside one activity, so the text they return
    stays in this process."""
    if len(items) < 2:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(items))) as pool:
        return list(pool.map(fn, items))


def summary_threads(
    integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime, bot_user_id: str | None
) -> list[SummaryThread]:
    """The threads to summarise for this person, each read in full, most relevant first. Empty when the flag is off,
    the bot cannot read channels, the sweep built no index today, or nothing moved."""
    if not wants_summary(integration, slack_user_id):
        return []
    slack = SlackIntegration(integration)
    if slack.missing_scopes(CHANNEL_SCOPES):
        logger.info("slack_app_daily_summary_skipped", reason="missing_bot_scopes", integration_id=integration.id)
        return []
    index = cached_index(integration)
    if not index:
        logger.info("slack_app_daily_summary_skipped", reason="no_index_today", integration_id=integration.id)
        return []
    channels = set(
        _member_channels(
            slack.client, types=_channel_types(slack), user=slack_user_id, wanted={root.channel_id for root in index}
        )
    )
    kept = pick_threads(index, slack_user_id, channels, since=since, bot_user_id=bot_user_id)
    if not kept:
        logger.info(
            "slack_app_daily_summary_skipped",
            reason="nothing_moved",
            integration_id=integration.id,
            person_channels=len(channels),
            indexed_roots=len(index),
        )
    read = parallel_map(lambda root: _summary_thread(slack, root, slack_user_id, bot_user_id), kept)
    return [thread for thread in read if thread is not None]


def pick_threads(
    roots: list[RootRef], slack_user_id: str, channels: set[str], *, since: datetime, bot_user_id: str | None = None
) -> list[RootRef]:
    """The person's own threads that moved come first, newest first. The rest of their channels fill the remaining
    places by Jev's score. A thread the app was tagged or replied in was already handled."""
    since_at = since.timestamp()
    moved = [
        root
        for root in roots
        if root.channel_id in channels and root.moved_at >= since_at and not root.involves(bot_user_id)
    ]
    # A root the person posted counts as theirs once someone replied to it.
    own = [
        root
        for root in moved
        if root.involves(slack_user_id) and (root.author != slack_user_id or root.latest_reply >= since_at)
    ]
    own.sort(key=lambda root: root.moved_at, reverse=True)
    others = [
        root
        for root in moved
        if root not in own and root.author != slack_user_id and root.score >= RANK_MIN_PROBABILITY
    ]
    others.sort(key=lambda root: (root.score, root.moved_at), reverse=True)
    return (own + others)[:THREADS_PER_PERSON]


def _index_key(integration: WorkspaceIntegration) -> str:
    return f"slack_app:daily_summary:index:{integration.integration_id}:{timezone.now().date().isoformat()}"


def cached_index(integration: WorkspaceIntegration) -> list[RootRef] | None:
    cached = cache.get(_index_key(integration))
    return [RootRef(**item) for item in cached] if isinstance(cached, list) else None


def build_workspace_index(integration: WorkspaceIntegration) -> int:
    """Reads and scores the roots of every channel the bot is in, once a day for the workspace, before the people in it
    run. Holds ids, counts and scores, never text. Returns how many roots the index holds; a build that is already
    done or under way today returns without reading Slack again."""
    slack = SlackIntegration(integration)
    if slack.missing_scopes(CHANNEL_SCOPES):
        logger.info("slack_app_daily_summary_index_skipped", reason="missing_bot_scopes", integration_id=integration.id)
        return 0
    key = _index_key(integration)
    cached = cache.get(key)
    if isinstance(cached, list):
        return len(cached)
    if not cache.add(f"{key}:lock", 1, BUILD_LOCK_SECONDS):
        logger.info("slack_app_daily_summary_index_skipped", reason="already_building", integration_id=integration.id)
        return 0
    client = slack.client
    channels = _member_channels(client, types=_channel_types(slack), limit=CHANNELS_PER_WORKSPACE)
    decision = consume(
        f"slack_app:daily_summary:history:{integration.integration_id}", HISTORY_BUDGET, cost=len(channels)
    )
    if isinstance(decision, BucketDecision) and not decision.allowed:
        # The retry has to be able to take the lock again.
        cache.delete(f"{key}:lock")
        raise DailySummaryRateLimited
    oldest = (timezone.now() - INDEX_LOOKBACK).timestamp()
    roots: list[RootRef] = []
    texts: list[str] = []
    for channel_id in channels:
        for message in _channel_roots(client, channel_id, oldest=oldest):
            roots.append(_root_ref(channel_id, message))
            texts.append(str(message.get("text") or "")[:ROOT_CHARS])
    # A root nobody replied to, that names nobody and that Jev passed over can never be picked, so it is not kept.
    kept = [
        root
        for root in _scored(integration, roots, texts)
        if root.reply_count or root.mentions or root.score >= RANK_MIN_PROBABILITY
    ]
    cache.set(key, [asdict(root) for root in kept], INDEX_TTL_SECONDS)
    logger.info(
        "slack_app_daily_summary_indexed",
        integration_id=integration.id,
        channels=len(channels),
        roots=len(roots),
        kept=len(kept),
    )
    return len(kept)


def _channel_types(slack: SlackIntegration) -> str:
    return "public_channel" if slack.missing_scopes(PRIVATE_CHANNEL_SCOPES) else "public_channel,private_channel"


def _member_channels(
    client: WebClient, *, types: str, user: str | None = None, wanted: set[str] | None = None, limit: int | None = None
) -> list[str]:
    """The channels ``user`` is in, or the bot itself when no user is named. A private channel shows only when the bot
    is in it too. Stops once every ``wanted`` channel is seen or ``limit`` channels are found."""
    channels: list[str] = []
    cursor = ""
    try:
        for _ in range(MEMBER_PAGES):
            response = client.users_conversations(
                **({"user": user} if user else {}), types=types, exclude_archived=True, limit=200, cursor=cursor or None
            )
            channels.extend(str(channel["id"]) for channel in response.get("channels") or [])
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor or (limit and len(channels) >= limit) or (wanted is not None and wanted <= set(channels)):
                break
    except (SlackApiError, SlackClientError, OSError):
        logger.warning("slack_app_daily_summary_channels_failed", exc_info=True)
    return channels[:limit] if limit else channels


def _channel_roots(client: WebClient, channel_id: str, *, oldest: float) -> list[dict[str, Any]]:
    try:
        response = client.conversations_history(channel=channel_id, oldest=str(oldest), limit=ROOTS_PER_CHANNEL)
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
    newest = sorted(range(len(roots)), key=lambda index: roots[index].moved_at, reverse=True)[
        :ROOTS_SCORED_PER_WORKSPACE
    ]
    client = build_system_one_client(
        model=RANK_MODEL,
        ai_product="slack_app",
        team_id=integration.team_id,
        properties={"slack_app_classifier": "daily_summary_rank", "slack_app_flow": "slack_app_daily_focus"},
        timeout=RANK_TIMEOUT_SECONDS,
        privacy_mode=True,
    )
    scores = [0.0] * len(roots)
    for start in range(0, len(newest), GATEWAY_MAX_QUESTIONS):
        keys = {f"r{index}": index for index in newest[start : start + GATEWAY_MAX_QUESTIONS]}
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


def _summary_thread(
    slack: SlackIntegration, root: RootRef, slack_user_id: str, bot_user_id: str | None
) -> SummaryThread | None:
    read = read_thread(slack.client, root.channel_id, root.ts, bot_user_id=bot_user_id, limit=SUMMARY_REPLIES_LIMIT)
    # The app answered in the thread, so it was a request to the app, which the person already got back.
    if read is None or read.app_took_part or not read.messages:
        return None
    return SummaryThread(
        channel_id=root.channel_id,
        ts=root.ts,
        text=thread_text(read.messages),
        involves_person=root.involves(slack_user_id) or any(m.get("user") == slack_user_id for m in read.messages),
        permalink=thread_permalink(slack, root.channel_id, root.ts),
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
