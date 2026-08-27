"""Slack message text processing helpers.

The bot strips its own self-mention and enriches every other `<@U…>` reference
with a `|displayname` label before handing the text to the agent — the agent
gets a human-readable name to reason about *and* a token it can echo verbatim to
ping the user back. The labeled form is how Slack delivers mentions inbound, but
it does not reliably notify when a bot posts it outbound, so the Slack relay
rewrites echoed `<@U_ID|displayname>` tokens back to the bare `<@U_ID>` on the
way out (see `products/tasks/backend/temporal/slack_relay/activities.py`).

Also houses ``collect_thread_messages`` (and its cached wrapper) — fetching the
full thread shape used by the agent context block lives next to the text logic
it depends on, kept out of ``api.py`` so the pure helpers stay testable in
isolation.

The outbound half lives here too: the small Block Kit builders and the reply
footer that says where to open a run and what produced it. All of it is what a
Slack message is made of, and none of it needs a client, so it stays testable
without one.
"""

import re
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from posthog.models.integration import Integration, SlackIntegration
from posthog.utils import absolute_uri

from products.slack_app.backend.services.model_catalogue import describe_run_model
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
    human-readable handle to reason about *and* the exact token it can echo
    verbatim to ping the user back. The labeled form does not reliably notify
    when a bot posts it outbound, so the Slack relay rewrites echoed tokens back
    to the bare `<@U_ID>` before posting.

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


_RE_LABELED_USER_MENTION = re.compile(r"<@([A-Z0-9]+)\|[^>]*>")


def normalize_labeled_mentions_to_bare(text: str) -> str:
    """Rewrite labeled `<@U_ID|display name>` mentions to the bare `<@U_ID>` for outbound posts.

    We feed the agent the labeled form so it can echo a token to ping a participant back, but
    that form only reliably notifies inbound: when a bot posts it, Slack does not consistently
    linkify it, so a display name containing a space renders as inert text and the user is never
    notified. The bare `<@U_ID>` is the canonical outbound mention — Slack resolves the current
    name itself. Only `<@…>` user mentions are rewritten; channel links (`<#C…|name>`),
    broadcast/subteam refs (`<!…>`), and URL links (`<https://…|label>`) keep their labels.
    """
    return _RE_LABELED_USER_MENTION.sub(r"<@\1>", text)


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


def _message_exists_cache_key(channel: str, ts: str) -> str:
    # Keyed on the Slack coordinates rather than the integration: the message either
    # exists in that channel or it doesn't, regardless of which install is asking.
    return f"slack_message_exists:{channel}:{ts}"


def slack_message_exists(
    client: WebClient,
    channel: str,
    ts: str,
    *,
    ttl: int = THREAD_REPLIES_CACHE_TTL_SECONDS,
) -> bool:
    """Whether a Slack message is still there.

    Asked with a one-message window on `ts` itself: Slack answers with that message when
    it is there and an empty list when it isn't. `conversations.replies` would answer a
    different question — its result also depends on whether a thread was ever started and
    on how Slack represents a deleted parent.

    Cached on the same short TTL as the thread snapshot: a burst of relay chunks for one
    reply collapses onto a single `conversations.history` call, while a message deleted
    mid-run is noticed within seconds.
    """
    key = _message_exists_cache_key(channel, ts)
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)

    try:
        response = client.conversations_history(channel=channel, latest=ts, oldest=ts, inclusive=True, limit=1)
        exists = bool(response.get("messages"))
    except Exception:
        # Rate limits, transient 5xx, a scope we happen to lack — none of these are
        # evidence the message is gone, and treating them as such would silence real
        # replies. Fail open and let the post itself surface any real problem.
        logger.warning("slack_app_message_exists_probe_failed", channel=channel, ts=ts, exc_info=True)
        return True

    try:
        cache.set(key, exists, timeout=ttl)
    except Exception:
        logger.warning("slack_app_message_exists_cache_set_failed", channel=channel, ts=ts, exc_info=True)
    return exists


def post_slack_thread_reply(
    client: WebClient,
    *,
    channel: str,
    thread_ts: str | None,
    trigger_ts: str | None = None,
    **kwargs: Any,
) -> Any:
    """Post a reply once confirmed the message it answers still exists.

    The single funnel for every `@PostHog` reply. A deleted prompt has nobody left to
    answer, and replies to one were seen landing at channel level rather than in the
    thread. Returns ``None`` when nothing was posted.

    Where the reply goes and what it answers are separate questions. ``thread_ts`` places
    it — falsy posts at channel root, which some replies do deliberately because a
    thread-anchored one is invisible to anyone not already reading that thread.
    ``trigger_ts`` is the message being answered, and defaults to the anchor. Pass it
    whenever the two differ, or a root-placed reply would go out unchecked.

    With neither set there is nothing to check — a slash command creates no message — so
    the reply posts unconditionally.
    """
    check_ts = trigger_ts or thread_ts
    if check_ts and not slack_message_exists(client, channel, check_ts):
        logger.warning(
            "slack_app_thread_reply_skipped_message_deleted",
            channel=channel,
            thread_ts=thread_ts,
            trigger_ts=trigger_ts,
        )
        return None
    if thread_ts:
        return client.chat_postMessage(channel=channel, thread_ts=thread_ts, **kwargs)
    return client.chat_postMessage(channel=channel, **kwargs)


# `conversations.replies` answers `thread_not_found` for a ts that no longer resolves to a
# message; `message_not_found` is carried alongside it because Slack uses that spelling on
# neighbouring methods and the two mean the same thing here.
_MISSING_THREAD_ERRORS = frozenset({"thread_not_found", "message_not_found"})


def messages_at_or_before(messages: list[dict[str, str]], bound_ts: str) -> list[dict[str, str]]:
    """Messages posted at or before ``bound_ts``.

    Slack `ts` values are decimal strings, compared as Decimals rather than floats so
    precision can't drop a message that sits on the bound. A message without a parseable
    `ts` is dropped: callers use this to answer "what had been said by then", and a
    message that can't be placed in time can't be part of that answer.
    """

    def at_or_before(ts: str) -> bool:
        try:
            return Decimal(ts) <= Decimal(bound_ts)
        except InvalidOperation:
            return False

    return [message for message in messages if at_or_before(message.get("ts", ""))]


def collect_thread_messages(
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    our_bot_id: str | None,
    until_ts: str | None = None,
) -> list[dict[str, str]]:
    """Fetch thread messages, strip bot mentions, and resolve user display names.

    ``until_ts`` clips the thread at a message, for a reader who forked the discussion
    at a point in time: what was said afterwards was not what they were looking at.
    Unbounded by default, which is what the mention path wants — it is answering the
    thread as it stands.

    A thread whose root no longer exists — the user deleted the message that triggered
    us — comes back empty rather than raising. Callers read an empty thread as "nothing
    to do"; letting `thread_not_found` escape instead would exhaust the activity's
    retries and land in the workflow's error handler, which announces the failure in
    Slack. There is nothing to announce: the prompt was retracted.
    """
    client = slack.client
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    try:
        thread_response = client.conversations_replies(channel=channel, ts=thread_ts)
    except SlackApiError as e:
        if e.response.get("error") not in _MISSING_THREAD_ERRORS:
            raise
        logger.warning("slack_app_thread_message_deleted", channel=channel, thread_ts=thread_ts)
        return []
    raw_messages: list[dict] = thread_response.get("messages", [])
    if until_ts:
        raw_messages = messages_at_or_before(raw_messages, until_ts)

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


# Query param a link we compose can carry to tell our own unfurler to leave it alone
# (honoured by `parse_posthog_resource_link`).
UNFURL_OPT_OUT_PARAM = "unfurl"


@dataclass(frozen=True)
class RunFooter:
    """What a reply can say about the run behind it.

    Constant for the life of a handler, so it is supplied once at construction rather
    than threaded through every posting method. An empty instance is the "say nothing"
    case, which is what every caller outside the footer rollout gets.
    """

    task_url: str | None = None
    desktop_url: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    def has_content(self) -> bool:
        """Whether this would render as anything.

        A caller checks it to skip the flag lookups behind a footer that can't appear.
        Spelled out rather than given as ``__bool__`` so that ``footer or RunFooter()``
        keeps meaning "None-coalesce" and cannot silently discard a partial instance.
        """
        return any((self.task_url, self.desktop_url, self.model))


def load_run_footer(run_id: str | UUID | None) -> RunFooter:
    """Describe a run for the footer.

    Never raises: the footer is the last thing added to an answer that is already
    written, so failing to describe the run must not cost the reader the answer.

    Describes the run in full, links included. Whether the reader may open them is
    ``viewer_has_code_access``'s question, asked where the reader is known.
    """
    # Deferred so the tasks product stays off this module's import path, matching
    # `model_catalogue`.
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415
    from products.tasks.backend.facade.run_config import parse_run_state  # noqa: PLC0415

    if not run_id:
        return RunFooter()
    try:
        run = get_task_run(run_id)
        if run is None:
            return RunFooter()
        state = parse_run_state(run.state)
        return RunFooter(
            task_url=_task_url(run.team_id, run.task_id, run.id),
            # The web bridge page, not the raw `posthog-code://` scheme: it redirects into the
            # desktop app when installed and offers a download when not, so a reader without
            # the app lands somewhere useful instead of a dead link. It also picks the right
            # scheme (prod vs dev) client-side, which a server-minted scheme link can't.
            desktop_url=_desktop_bridge_url(run.task_id),
            model=state.model,
            reasoning_effort=state.reasoning_effort,
        )
    except Exception:
        logger.exception("slack_app_run_footer_load_failed", run_id=str(run_id))
        return RunFooter()


def reply_footer_block(footer: RunFooter, configure_url: str | None = None) -> dict[str, Any] | None:
    """The footer as a `context` block, or `None` when there is nothing to say.

    The answer itself is the message, so this is muted rather than competing with the
    prose. A run with no links and no pinned model contributes no segments and gets no
    trailing line at all.
    """
    segments: list[str] = []
    if footer.task_url:
        segments.append(f"<{footer.task_url}|View on web>")
    if footer.desktop_url:
        segments.append(f"<{footer.desktop_url}|View on desktop>")
    if footer.model:
        segments.append(describe_run_model(footer.model, footer.reasoning_effort))
    if configure_url:
        segments.append(f"<{configure_url}|Configure>")
    if not segments:
        return None
    return context_block(" · ".join(segments))


def fork_menu_actions_block(element: dict[str, Any]) -> dict[str, Any]:
    """The fork menu as a standalone block, for replies with no section to hang it on.

    A streamed answer arrives as markdown chunks and the chart delivery puts the answer
    in the card message, so neither has a `section` whose accessory the menu could be.
    Costs a line, which is why the plain-post path prefers the accessory.
    """
    return {"type": "actions", "elements": [element]}


FORK_THREAD_ACTION_ID = "slack_app_fork_thread"


def fork_menu_element(integration_id: int) -> dict[str, Any]:
    """The overflow menu the footer carries as its accessory.

    An overflow renders as a bare "…" with no label, which is as close to invisible as
    an interactive element gets — the answer above it is what the reader came for. It
    also has somewhere to put the next destination ("fork to a channel") without
    growing a second control.

    Returned as a bare element rather than wrapped in an `actions` block so it can be a
    `section` accessory, which is what puts it on the footer's own line. Slack offers no
    inline interactive element, so an accessory — right-aligned beside the text — is as
    close to trailing the footer as Block Kit gets.

    The option value carries the integration so the cross-region interactivity router
    can tell whose click this is. Everything else the fork needs — the channel, and the
    thread the reply is sitting in — rides on the `block_actions` payload.
    """
    return {
        "type": "overflow",
        "action_id": FORK_THREAD_ACTION_ID,
        "options": [
            {
                "text": {"type": "plain_text", "text": "Fork to DM", "emoji": True},
                "value": json.dumps({"integration_id": integration_id}),
            }
        ],
    }


def thread_permalink(slack: SlackIntegration, channel: str, thread_ts: str) -> str | None:
    """Permalink for a thread, or `None` if Slack won't give us one.

    Best-effort by design: a permalink is a convenience link on a task and a pointer in
    a forked run's context, never something a run depends on.
    """
    try:
        response = slack.client.chat_getPermalink(channel=channel, message_ts=thread_ts)
        if response.get("ok"):
            return response["permalink"]
    except Exception:
        logger.warning("slack_app_permalink_failed", channel=channel, thread_ts=thread_ts)
    return None


def context_block(text: str) -> dict[str, Any]:
    """A line of muted supporting text.

    Block Kit has no footer block; `context` is what renders small and grey under the
    content it describes.
    """
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def app_home_url(integration: Integration) -> str | None:
    """Deep link to this install's Home tab, where the model picker lives.

    The native `slack://` form rather than the https `app_redirect` one: the reader is
    already in Slack, so this opens the tab in place instead of bouncing them through a
    browser — and Slack doesn't unfurl a non-http scheme, so it costs no preview card.

    Needs the app id (`A…`), which the OAuth exchange already persisted on the
    integration, so this stays correct even where more than one Slack app is in play. A
    row installed by some other path may not carry it, which simply means no link.
    """
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"slack://app?team={integration.integration_id}&id={app_id}&tab=home"


def personal_integrations_url(team_id: int) -> str:
    """Where someone connects their own GitHub, so @PostHog opens pull requests as them.

    Connecting requires an authenticated PostHog session, so every surface that asks for it
    deep-links to this settings page instead of starting an OAuth flow from Slack.
    """
    return _public_url(f"/project/{team_id}/settings/user-personal-integrations")


def project_web_url(team_id: int) -> str:
    """Absolute ``/project/<id>`` base for links into this project's PostHog app."""
    return _public_url(f"/project/{team_id}")


def _task_url(team_id: int, task_id: UUID, run_id: UUID) -> str:
    # `unfurl=false` asks our own link unfurler to leave this one alone: the footer already
    # says what the card would, right next to the link.
    return _public_url(f"/project/{team_id}/tasks/{task_id}?runId={run_id}&{UNFURL_OPT_OUT_PARAM}=false")


def _desktop_bridge_url(task_id: UUID) -> str:
    # `/code/task/<id>` is the public bridge scene (see `CodeTaskLink`), not the desktop
    # app's own route. `unfurl=false` keeps our unfurler off it — the footer already names
    # the run right beside the link.
    return _public_url(f"/code/task/{task_id}?{UNFURL_OPT_OUT_PARAM}=false")


def _public_url(path: str) -> str:
    # Mirrors the Slack onboarding links: in local dev the tunnel is what makes a link
    # posted into Slack actually reachable.
    if settings.DEBUG and settings.NGROK_URL:
        return f"{settings.NGROK_URL.rstrip('/')}{path}"
    return absolute_uri(path)


def viewer_has_code_access(integration: Integration, slack_user_id: str | None) -> bool:
    """Whether the Slack identity reading this can open a PostHog Code link.

    Asked about the reader rather than the task's creator: the two can differ, and a link
    is only useful to the person looking at it. Fail closed — an unlinked identity or a
    flag-service error means no link rather than one that dead-ends.
    """
    from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user  # noqa: PLC0415
    from products.tasks.backend.facade.access import get_desktop_access_decision  # noqa: PLC0415

    if not slack_user_id:
        return False
    try:
        user = find_linked_posthog_user(
            slack_user_id=slack_user_id,
            slack_team_id=integration.integration_id,
            candidate_org_ids={integration.team.organization_id},
        )
        if user is None:
            return False
        return get_desktop_access_decision(user, integration.team.organization).allowed
    except Exception:
        logger.exception("slack_app_viewer_code_access_check_failed", integration_id=integration.id)
        return False
