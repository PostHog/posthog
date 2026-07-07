"""Slack message text processing helpers.

The bot strips its own self-mention and enriches every other `<@U…>` reference
with a `|displayname` label before handing the text to the agent. Slack accepts
the labeled form `<@U_ID|displayname>` on both inbound and outbound messages —
the agent gets a human-readable name to reason about *and* a wire-format token
it can echo verbatim to ping the user back, so no outbound transformation is
needed.

Also houses ``collect_thread_messages`` (and its cached wrapper) — fetching the
full thread shape used by the agent context block lives next to the text logic
it depends on, kept out of ``api.py`` so the pure helpers stay testable in
isolation.
"""

import re
from typing import Any

from django.core.cache import cache

import structlog
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.services.slack_user_info import get_cached_bot_user_id, get_slack_user_info

logger = structlog.get_logger(__name__)

# Short TTL keeps a burst of follow-ups (chatty thread, fast classifier-then-forwarder
# pipeline, multiple participants typing) collapsed onto a single Slack
# `conversations.replies` call, without keeping stale snapshots around long enough to
# matter for downstream decisions. The cache exists to absorb bursts, not to act as a
# source of truth — anything that depends on the very latest thread state should
# fetch without the cache.
THREAD_REPLIES_CACHE_TTL_SECONDS = 10


def resolve_user_mentions_text(
    slack: SlackIntegration,
    integration: Integration,
    text: str,
    *,
    strip_bot_user_id: str | None = None,
) -> str:
    """Label human `<@U…>` mentions with display names; drop every bot mention.

    Slack delivers events with bare `<@U_ID>` references — opaque to an LLM,
    and easily paraphrased away into plain prose. For real users we enrich to
    Slack's labeled form `<@U_ID|displayname>`: the agent gets both a
    human-readable handle to reason about *and* the exact wire-format token it
    can echo verbatim to ping the user back. Slack accepts the labeled form on
    the way out, so no outbound transformation is needed.

    Bot users (our own, plus any other workspace bot — Grafana, GitHub, etc.)
    are stripped entirely. There's nothing useful for the agent to do with a
    bot mention, and echoing it would re-ping the bot. The `is_bot` flag comes
    from `users.info` via the cached profile; `strip_bot_user_id` is a fast
    path for the trigger's own self-mention that avoids the lookup.

    Wire format alone can't distinguish a bot user ID from a human's — both
    are `U…`-prefixed. The flag is the only authoritative signal.
    """
    cache: dict[str, tuple[str, bool]] = {}

    def resolve_user(uid: str) -> tuple[str, bool]:
        if uid not in cache:
            try:
                user_info = get_slack_user_info(slack, integration, uid)
                user = user_info.get("user", {})
                profile = user.get("profile", {})
                display = profile.get("display_name") or profile.get("real_name") or "Unknown"
                cache[uid] = (display, bool(user.get("is_bot")))
            except Exception:
                # Lookup failed — degrade to a labeled mention so a ping still
                # works; treating an unknown user as a bot would silently drop
                # a real user's mention, which is the bug this module exists
                # to prevent.
                cache[uid] = ("Unknown", False)
        return cache[uid]

    def replace_mention(match: re.Match) -> str:
        uid = match.group(1)
        if strip_bot_user_id and uid == strip_bot_user_id:
            return ""
        display, is_bot = resolve_user(uid)
        if is_bot:
            return ""
        return f"<@{uid}|{display}>"

    resolved = re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)
    # Tidy gaps left where bot mentions were removed.
    resolved = re.sub(r"[ \t]{2,}", " ", resolved).strip()
    return resolved


def decode_slack_event_text(slack: SlackIntegration, integration: Integration, text: str) -> str:
    """Strip the bot's own self-mention from a Slack event and label the rest for the agent.

    Trigger sites all want the same thing: drop the bot's self-ping (it's just
    the activation, no information for the agent) and enrich every other
    `<@U…>` reference with a `|displayname` label so the agent can echo the
    token verbatim to ping the user back. Centralised here so a new trigger
    handler can't drift back into the original mention-eating bug.
    """
    bot_user_id = get_cached_bot_user_id(slack, integration)
    return resolve_user_mentions_text(slack, integration, text, strip_bot_user_id=bot_user_id).strip()


def labeled_mentions_to_display_names(text: str) -> str:
    """Render labeled `<@U…|name>` mentions as plain `@name` for human-facing display.

    The labeled wire format is what we feed the agent so its replies round-trip as
    real Slack pings, but in human-facing contexts — task titles, PR titles, anywhere
    a UI surfaces the string without Slack rendering — the angle-bracket form shows
    up as literal noise. This unwraps it back to the readable form.
    """
    return re.sub(r"<@[A-Z0-9]+\|([^>]+)>", r"@\1", text)


def flatten_block_text(node: Any) -> list[str]:
    """Best-effort plain-text extraction from a Slack block-kit subtree.

    Slack alert posts (subscriptions, log alerts, hog-function destinations) often
    put the substantive content in `blocks` while the top-level `text` field is a
    short fallback (or empty). Walking the block tree lets us surface that content
    to the agent. Always wrap call sites in try/except — Slack block schemas evolve.
    """
    if node is None:
        return []
    if isinstance(node, str):
        stripped = node.strip()
        return [stripped] if stripped else []
    if isinstance(node, list):
        out: list[str] = []
        for item in node:
            out.extend(flatten_block_text(item))
        return out
    if isinstance(node, dict):
        # `context` blocks can carry useful labels — recurse into `elements` only.
        if node.get("type") == "context":
            return flatten_block_text(node.get("elements"))
        # Skip interactive/decorative blocks that carry no information for the agent.
        if node.get("type") in ("actions", "divider", "image"):
            return []
        out = []
        for key in ("text", "fields", "elements", "title", "pretext", "fallback"):
            if key in node:
                out.extend(flatten_block_text(node[key]))
        return out
    return []


def extract_message_text(msg: dict) -> str:
    # Always include `text` and `blocks`/`attachments`: PostHog's own alert templates put
    # the headline in `text` and the values/details in blocks. Dedup so a string repeated
    # across both (e.g. text == header block) shows up once.
    pieces: list[str] = []
    text = (msg.get("text") or "").strip()
    if text:
        pieces.append(text)

    blocks = msg.get("blocks") or []
    attachments = msg.get("attachments") or []
    try:
        pieces.extend(flatten_block_text(blocks))
    except Exception:
        logger.warning("slack_thread_block_flatten_failed", exc_info=True)
    try:
        pieces.extend(flatten_block_text(attachments))
    except Exception:
        logger.warning("slack_thread_attachment_flatten_failed", exc_info=True)

    seen: set[str] = set()
    deduped: list[str] = []
    for piece in pieces:
        if piece and piece not in seen:
            seen.add(piece)
            deduped.append(piece)
    return "\n".join(deduped)


def resolve_bot_author_label(msg: dict) -> str:
    bot_profile = msg.get("bot_profile") or {}
    return bot_profile.get("name") or msg.get("username") or "Bot"


def _thread_replies_cache_key(integration_id: int, channel: str, thread_ts: str) -> str:
    return f"slack_thread_replies:{integration_id}:{channel}:{thread_ts}"


def collect_thread_messages(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    our_bot_id: str | None,
) -> list[dict[str, str]]:
    """Fetch thread messages, strip bot mentions, and resolve user display names."""
    client = slack.client
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    thread_response = client.conversations_replies(channel=channel, ts=thread_ts)
    raw_messages: list[dict] = thread_response.get("messages", [])

    user_cache: dict[str, str] = {}

    def resolve_user(uid: str) -> str:
        if uid not in user_cache:
            try:
                user_info = get_slack_user_info(slack, integration, uid)
                profile = user_info.get("user", {}).get("profile", {})
                user_cache[uid] = profile.get("display_name") or profile.get("real_name") or "Unknown"
            except Exception:
                user_cache[uid] = "Unknown"
        return user_cache[uid]

    messages = []
    for index, msg in enumerate(raw_messages):
        # Skip our own bot's posts to avoid loops where the agent ingests its own replies.
        # Never skip the thread root: the agent only ever posts as a reply, so msg 0 is
        # always the originating message (e.g. a PostHog alert) that's the actual context
        # for the task. Filtering it by bot_id breaks workspaces where the alerting Slack
        # app and the `@PostHog` code app share an installation identity.
        if index > 0 and our_bot_id and msg.get("bot_id") == our_bot_id:
            continue

        user_id = msg.get("user")
        if user_id:
            username = resolve_user(user_id)
        elif msg.get("bot_id"):
            username = resolve_bot_author_label(msg)
        else:
            username = "Unknown"

        text = resolve_user_mentions_text(slack, integration, extract_message_text(msg))
        # `ts` lets downstream callers distinguish the initiator message from surrounding thread
        # context, since `app_mention` events surface only the initiator's ts. `user_id` is the
        # raw `U…` Slack id so downstream prompt builders can render the labeled `<@U…|name>`
        # mention form for each message author — the same wire-format token the agent can echo
        # back to ping that user.
        messages.append({"user": username, "user_id": user_id or "", "text": text, "ts": msg.get("ts") or ""})

    return messages


def cached_collect_thread_messages(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    our_bot_id: str | None,
    *,
    ttl: int = THREAD_REPLIES_CACHE_TTL_SECONDS,
) -> list[dict[str, str]]:
    """Cached version of ``collect_thread_messages`` keyed by (integration, channel, thread_ts).

    A bursty thread — fast classifier-then-forwarder pipeline, many follow-ups within
    seconds, multiple participants typing — would otherwise re-fetch the same thread
    several times in quick succession. The 10-second default TTL collapses those into
    a single ``conversations.replies`` call while staying well inside Slack's Tier 3
    rate budget and any reasonable staleness tolerance: a message that arrives during
    the cache window is the one being processed (it's a parameter to the workflow,
    not something we'd discover from the fetch), and anything that arrives *after*
    is processed by a *subsequent* workflow run that lands after the cache has expired
    or repopulated.

    On a cache miss the underlying fetch can raise; we let that propagate so the
    activity-level retry policy and rate-limit retry handler do the right thing. We
    do NOT serve a stale-on-error fallback in v1 — it would mask sustained outages.
    """
    key = _thread_replies_cache_key(integration.id, channel, thread_ts)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = collect_thread_messages(slack, integration, channel, thread_ts, our_bot_id)
    try:
        cache.set(key, result, timeout=ttl)
    except Exception:
        # Cache backend hiccups should not fail the activity — the fresh result is in hand.
        logger.warning(
            "slack_app_thread_replies_cache_set_failed",
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            exc_info=True,
        )
    return result


def invalidate_thread_messages_cache(integration_id: int, channel: str, thread_ts: str) -> None:
    """Drop the cached thread snapshot — call when downstream code needs a guaranteed fresh fetch."""
    try:
        cache.delete(_thread_replies_cache_key(integration_id, channel, thread_ts))
    except Exception:
        logger.warning(
            "slack_app_thread_replies_cache_delete_failed",
            integration_id=integration_id,
            channel=channel,
            thread_ts=thread_ts,
            exc_info=True,
        )
