"""Slack message matching and firing for Loops.

The entry point is ``handle_slack_message_for_loops``, called from the Slack Events API
handler (``products.slack_app.backend.api``) for ``message`` events, after signature
verification and region routing. It is the Slack counterpart of ``loop_github_events``:
match the event against the team's stored triggers deterministically, then hand a matched
trigger to the one ``loop_runs.fire_loop`` choke point.

Unlike GitHub, Slack has no per-event signature of who may act, so authorization is part
of the trigger's own config (``allowed_posters``). A matched trigger fires an unattended
run holding the loop owner's credentials, and the message text lands in that run's prompt,
so the poster gate is what stops an arbitrary channel member steering it.
"""

import time
from collections.abc import Callable
from typing import Any, Literal

import structlog
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.redis import get_client
from posthog.user_permissions import UserPermissions

from products.tasks.backend.logic.services import loop_runs
from products.tasks.backend.models import Loop, LoopTrigger

logger = structlog.get_logger(__name__)

# Slack truncates nothing for us, and an alert bot can post a very long block payload.
# The excerpt bounds what reaches the prompt; the search budget bounds what we scan.
_EXCERPT_LIMIT = 2000
_SEARCH_TEXT_LIMIT = 8000

# Request-level flood control ahead of the per-loop/team rate caps, sized above a busy
# channel's real volume. Slack's message firehose is chattier than GitHub's webhooks, so
# this is per (workspace, channel) rather than per workspace.
_EVENT_THROTTLE_LIMIT = 600
_EVENT_THROTTLE_WINDOW_SECONDS = 300

# Who a `slack` trigger accepts a firing message from.
POSTER_MODE_ORG_MEMBERS = "org_members"
POSTER_MODE_LOOP_OWNER = "loop_owner"
POSTER_MODE_SLACK_USER_IDS = "slack_user_ids"
ALLOWED_POSTER_MODES = (POSTER_MODE_ORG_MEMBERS, POSTER_MODE_LOOP_OWNER, POSTER_MODE_SLACK_USER_IDS)

LoopSlackEventOutcome = Literal["matched", "deduped", "skipped", "throttled", "fired", "unauthorized", "error"]

LOOP_SLACK_EVENT_TOTAL = Counter(
    "posthog_tasks_loop_slack_event_total",
    "Slack message matching/firing decisions for Loops, keyed by outcome",
    labelnames=["outcome"],
)


def _observe_slack_event(outcome: LoopSlackEventOutcome) -> None:
    LOOP_SLACK_EVENT_TOTAL.labels(outcome=outcome).inc()


# Short enough that a newly saved trigger goes live promptly, long enough that a busy
# channel doesn't re-run the join per message.
_HAS_TRIGGERS_CACHE_SECONDS = 60


def slack_workspace_has_loop_triggers(slack_team_id: str) -> bool:
    """Whether any enabled `slack` trigger exists for this Slack workspace, cached.

    The Slack event handler asks this before doing anything else with a channel message.
    Almost every message belongs to a workspace with no triggers at all, and that case has
    to stay cheap: without the cache, opening the handler to top-level posts would put a
    database query on the whole firehose. A new trigger can take up to
    ``_HAS_TRIGGERS_CACHE_SECONDS`` to start firing. Fails open, so a Redis outage costs a
    query rather than silently disabling every trigger.

    A region holding no install for the workspace answers ``True``, not ``False``. It cannot
    see the other region's triggers, and a ``False`` there would drop the message before the
    region gate that would have forwarded it — so a workspace installed in the other region
    would silently only ever fire on thread replies. The forwarded copy pays the real check in
    the region that owns the install.
    """
    key = f"loop_slack_events:has_triggers:{slack_team_id}"
    try:
        client = get_client()
        cached = client.get(key)
        if cached is not None:
            return cached in (b"1", "1")
    except Exception:
        logger.warning("loop_slack_event_trigger_cache_read_failed", slack_team_id=slack_team_id, exc_info=True)

    local_integrations = Integration.objects.filter(kind="slack", integration_id=slack_team_id)
    exists = (
        not local_integrations.exists()
        or LoopTrigger.objects.unscoped()
        .filter(
            type=LoopTrigger.TriggerType.SLACK,
            enabled=True,
            loop__enabled=True,
            loop__deleted=False,
            slack_integration_id__in=local_integrations.values("id"),
        )
        .exists()
    )

    try:
        get_client().set(key, b"1" if exists else b"0", ex=_HAS_TRIGGERS_CACHE_SECONDS)
    except Exception:
        logger.warning("loop_slack_event_trigger_cache_write_failed", slack_team_id=slack_team_id, exc_info=True)
    return exists


def handle_slack_message_for_loops(
    *,
    event: dict[str, Any],
    slack_team_id: str,
    event_id: str,
    integrations: list[Integration],
    resolve_poster_user_id: Callable[[], int | None],
) -> int:
    """Fire every enabled `slack` trigger this message matches. Returns how many matched.

    ``integrations`` is the set of Slack integrations the caller has already decided may act on
    this message — health-filtered, and gated on the rollout flag per organization. Matching
    never widens beyond it, so a workspace connected to several organizations can't fire a loop
    for one whose install is broken or whose flag is off.

    ``resolve_poster_user_id`` is called at most once, and only after a trigger has already
    matched on channel and content: resolving a Slack user to a PostHog one costs a
    ``users.info`` round trip, and the common case is a message that matches nothing.
    """
    channel = event.get("channel")
    if not isinstance(channel, str) or not channel:
        _observe_slack_event("skipped")
        return 0

    # Slack omits `event_id` on some delivery shapes, and an empty fire key would collide
    # across every message for a trigger — only the first would ever fire. (channel, ts)
    # identifies a message just as uniquely.
    fire_key = event_id or f"{channel}:{event.get('ts')}"

    if _slack_events_throttled(slack_team_id, channel):
        logger.warning("loop_slack_event_throttled", slack_team_id=slack_team_id, channel=channel)
        _observe_slack_event("throttled")
        return 0

    # A reply inside a thread that already belongs to an agent run is that run's
    # conversation, not new work: firing there would let a loop's own report re-trigger it.
    if _is_agent_thread_reply(event):
        _observe_slack_event("skipped")
        return 0

    search_text = _message_search_text(event)
    summary = _build_event_summary(event, slack_team_id, search_text)
    poster = _MemoizedPoster(resolve_poster_user_id)

    matched = 0
    for integration in integrations:
        matched += _match_and_fire_for_integration(
            integration, channel, event, slack_team_id, fire_key, search_text, summary, poster
        )

    if matched:
        logger.info(
            "loop_slack_event_matched",
            slack_team_id=slack_team_id,
            channel=channel,
            event_id=event_id,
            matched_triggers=matched,
        )
    return matched


class _MemoizedPoster:
    """One ``users.info``/membership resolution per event, shared across every trigger it
    is checked against. ``None`` is a real answer (unresolvable poster), so a separate
    ``_resolved`` flag distinguishes it from "not looked up yet"."""

    def __init__(self, resolve: Callable[[], int | None]) -> None:
        self._resolve = resolve
        self._resolved = False
        self._user_id: int | None = None

    def user_id(self) -> int | None:
        if not self._resolved:
            self._user_id = self._resolve()
            self._resolved = True
        return self._user_id


def _match_and_fire_for_integration(
    integration: Integration,
    channel: str,
    event: dict[str, Any],
    slack_team_id: str,
    fire_key: str,
    search_text: str,
    summary: dict[str, Any],
    poster: _MemoizedPoster,
) -> int:
    """Match and fire triggers for one team's integration, isolated from other teams.

    A Slack workspace can be connected to several PostHog teams, so a lookup failure for
    one must not stop the same message firing loops for the others.
    """
    try:
        triggers = (
            LoopTrigger.objects.for_team(integration.team_id)
            .filter(
                type=LoopTrigger.TriggerType.SLACK,
                enabled=True,
                loop__enabled=True,
                loop__deleted=False,
                slack_integration_id=integration.id,
                slack_channel_ids__contains=[channel],
            )
            # `loop__team` rides along for the poster's project-access check, which would
            # otherwise fetch the team once per matched trigger.
            .select_related("loop", "loop__team")
        )
    except Exception as e:
        logger.exception("loop_slack_event_team_lookup_failed", team_id=integration.team_id, fire_key=fire_key)
        capture_exception(e)
        _observe_slack_event("error")
        return 0

    matched = 0
    for trigger in triggers:
        if not _trigger_filters_match(trigger, search_text, event):
            continue
        # Content matched, so the poster gate is worth paying for now.
        if not _poster_allowed(trigger, event, poster):
            logger.info("loop_slack_event_poster_not_allowed", trigger_id=str(trigger.id), fire_key=fire_key)
            _observe_slack_event("unauthorized")
            continue

        matched += 1
        _observe_slack_event("matched")
        _fire_matched_trigger(trigger, event, slack_team_id, fire_key, summary)

    return matched


def _fire_matched_trigger(
    trigger: LoopTrigger, event: dict[str, Any], slack_team_id: str, fire_key: str, summary: dict[str, Any]
) -> None:
    try:
        trigger_context = loop_runs.render_trigger_context("slack", summary, trigger.loop)
        result = loop_runs.fire_loop(
            loop=trigger.loop,
            trigger=trigger,
            fire_key=fire_key,
            trigger_context=trigger_context,
            slack_thread_target=_thread_target(trigger, event, slack_team_id),
        )
        _observe_slack_event(_fire_result_outcome(result.reason))
    except Exception as e:
        logger.exception("loop_slack_event_fire_failed", trigger_id=str(trigger.id), fire_key=fire_key)
        capture_exception(e)
        _observe_slack_event("error")


def _fire_result_outcome(reason: str) -> LoopSlackEventOutcome:
    if reason == "created":
        return "fired"
    if reason == "deduped":
        return "deduped"
    return "skipped"


def _thread_target(trigger: LoopTrigger, event: dict[str, Any], slack_team_id: str) -> dict[str, Any]:
    """Where the run reports back. A top-level post opens a new thread under itself
    (``thread_ts`` is the message's own ``ts``); a reply keeps its existing thread."""
    ts = str(event.get("ts") or "")
    thread_ts = event.get("thread_ts")
    return {
        "integration_id": trigger.slack_integration_id,
        "slack_workspace_id": slack_team_id,
        "channel": str(event.get("channel") or ""),
        "thread_ts": thread_ts if isinstance(thread_ts, str) and thread_ts else ts,
        "user_message_ts": ts,
        "mentioning_slack_user_id": str(event.get("user") or ""),
    }


def _slack_events_throttled(slack_team_id: str, channel: str) -> bool:
    """Fixed-window counter per (workspace, channel), keyed on the window bucket so a missed
    expiry can never wedge the throttle shut. Fails open: a Redis outage must not drop fires."""
    try:
        client = get_client()
        bucket = int(time.time() // _EVENT_THROTTLE_WINDOW_SECONDS)
        key = f"loop_slack_events:throttle:{slack_team_id}:{channel}:{bucket}"
        count = client.incr(key)
        if count == 1:
            client.expire(key, _EVENT_THROTTLE_WINDOW_SECONDS * 2)
        return count > _EVENT_THROTTLE_LIMIT
    except Exception:
        logger.warning("loop_slack_event_throttle_check_failed", slack_team_id=slack_team_id, exc_info=True)
        return False


def _is_agent_thread_reply(event: dict[str, Any]) -> bool:
    from products.slack_app.backend.models import (  # noqa: PLC0415 (product boundary; keeps slack_app off this module's import path)
        SlackThreadTaskMapping,
    )

    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    if not isinstance(thread_ts, str) or not thread_ts or thread_ts == ts:
        return False
    return SlackThreadTaskMapping.objects.filter(channel=event.get("channel"), thread_ts=thread_ts).exists()


def _is_app_authored(event: dict[str, Any]) -> bool:
    """Whether an app, not a person typing, is behind this message. Mirrors the Slack app's
    own authorship check — a bot token, an incoming webhook, or an app posting with a user
    token. Such a message has no human identity to resolve, so only an explicit
    ``slack_user_ids`` allowlist can admit it."""
    return bool(
        event.get("bot_id")
        or event.get("bot_profile")
        or event.get("app_id")
        or event.get("subtype") == "bot_message"
        or event.get("user") == "USLACKBOT"
    )


def _event_author_ids(event: dict[str, Any]) -> set[str]:
    """Every identity Slack attributes the message to. A bot posts under a ``bot_id`` and
    often no ``user`` at all, so an allowlist has to be matchable against either."""
    bot_profile = event.get("bot_profile")
    candidates = [
        event.get("user"),
        event.get("bot_id"),
        bot_profile.get("id") if isinstance(bot_profile, dict) else None,
        event.get("app_id"),
    ]
    return {str(value) for value in candidates if isinstance(value, str) and value}


def _poster_allowed(trigger: LoopTrigger, event: dict[str, Any], poster: _MemoizedPoster) -> bool:
    config = trigger.config if isinstance(trigger.config, dict) else {}
    allowed = config.get("allowed_posters")
    allowed = allowed if isinstance(allowed, dict) else {}
    mode = allowed.get("mode", POSTER_MODE_ORG_MEMBERS)

    if mode == POSTER_MODE_SLACK_USER_IDS:
        permitted = allowed.get("slack_user_ids")
        if not isinstance(permitted, list):
            return False
        return bool(_event_author_ids(event).intersection(permitted))

    # The remaining modes authorize a human, so an app-authored message can never satisfy
    # them: there is nobody to resolve, and an app posting on a person's behalf is
    # indistinguishable from that person typing.
    if _is_app_authored(event):
        return False

    user_id = poster.user_id()
    if user_id is None:
        return False

    if mode == POSTER_MODE_LOOP_OWNER:
        return user_id == trigger.loop.created_by_id

    return _has_project_access(user_id, trigger.loop)


def _has_project_access(user_id: int, loop: Loop) -> bool:
    """Whether the poster can reach the loop's project — the same bar `loop_runs` holds the
    loop's own owner to.

    Organization membership alone is not enough on two counts. A Slack workspace can be
    connected to several organizations, so "a member of some connected org" says nothing about
    this loop's. And the project itself may be access-controlled, in which case an org member
    without access to it could otherwise fire a run there and read its report in the channel.
    """
    poster = User.objects.filter(id=user_id, is_active=True).first()
    if poster is None:
        return False
    return UserPermissions(user=poster, team=loop.team).current_team.effective_membership_level is not None


def _trigger_filters_match(trigger: LoopTrigger, search_text: str, event: dict[str, Any]) -> bool:
    """JSON `filters` evaluated last, after the DB query already matched the promoted
    `(slack_integration_id, slack_channel_ids)` columns."""
    config = trigger.config if isinstance(trigger.config, dict) else {}
    filters = config.get("filters")
    return _filters_match(filters if isinstance(filters, dict) else {}, search_text, event)


def _filters_match(filters: dict[str, Any], search_text: str, event: dict[str, Any]) -> bool:
    keywords = filters.get("keywords")
    if keywords and not _keywords_match(keywords, search_text):
        return False

    payload_conditions = filters.get("payload")
    if payload_conditions and not _payload_matches(payload_conditions, event):
        return False

    return True


def _keywords_match(keywords: list[Any], search_text: str) -> bool:
    """Case-insensitive substring match, OR across keywords — the same shape as the GitHub
    trigger's `actions`/`labels` lists. Values arrive lowercased from the trigger serializer."""
    haystack = search_text.lower()
    return any(isinstance(keyword, str) and keyword in haystack for keyword in keywords)


def _resolve_payload_path(payload: dict[str, Any], path: str) -> Any:
    """Walk a dot-path through nested objects. Objects only: a segment landing on a list or a
    scalar resolves to nothing, mirroring the GitHub trigger's payload conditions."""
    current: Any = payload
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _payload_leaf_as_string(value: Any) -> str | None:
    # bool before int: `isinstance(True, int)` is True, and "true" is what an author writes.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return None


def _payload_matches(conditions: list[Any], event: dict[str, Any]) -> bool:
    """Every condition's dot-path must resolve to a scalar whose string form is one of its
    expected values (AND across conditions, OR within one)."""
    for condition in conditions:
        if not isinstance(condition, dict):
            return False
        leaf = _payload_leaf_as_string(_resolve_payload_path(event, str(condition.get("path", ""))))
        if leaf is None or leaf not in (condition.get("equals") or []):
            return False
    return True


def _collect_text_values(node: Any, collected: list[str], budget: int) -> int:
    """Depth-first sweep for the ``text`` leaves of a Block Kit / attachment tree.

    Alert integrations (incident tooling, monitoring relays) post their content as blocks
    and attachments with an empty top-level ``text``, so matching only ``event["text"]``
    would never see the words a keyword filter is written against.
    """
    if budget <= 0:
        return budget
    if isinstance(node, str):
        collected.append(node)
        return budget - len(node)
    if isinstance(node, list):
        for item in node:
            budget = _collect_text_values(item, collected, budget)
        return budget
    if isinstance(node, dict):
        for key in ("text", "fallback", "pretext", "title", "value", "fields", "elements", "blocks", "attachments"):
            if key in node:
                budget = _collect_text_values(node[key], collected, budget)
    return budget


def _message_search_text(event: dict[str, Any]) -> str:
    """The text a keyword filter is matched against: the message body plus whatever its
    attachments and blocks render as."""
    collected: list[str] = []
    budget = _SEARCH_TEXT_LIMIT
    for key in ("text", "attachments", "blocks"):
        value = event.get(key)
        if value:
            budget = _collect_text_values(value, collected, budget)
        if budget <= 0:
            break
    return "\n".join(collected)[:_SEARCH_TEXT_LIMIT]


def _excerpt(text: Any, limit: int = _EXCERPT_LIMIT) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_event_summary(event: dict[str, Any], slack_team_id: str, search_text: str) -> dict[str, Any]:
    """Compact, agent-safe summary of the message for trigger_context rendering.

    Only the fields useful as run context are kept, with free text excerpted. The rendered
    text is the same one the filters matched, so an alert posted as blocks reaches the run
    as readable content rather than a raw Block Kit tree.
    """
    bot_profile = event.get("bot_profile")
    summary: dict[str, Any] = {
        "event": "slack_message",
        "workspace_id": slack_team_id,
        "channel": event.get("channel"),
        "ts": event.get("ts"),
        "thread_ts": event.get("thread_ts"),
        "user": event.get("user"),
        "text": _excerpt(search_text),
    }
    if isinstance(bot_profile, dict):
        summary["bot"] = {"id": bot_profile.get("id"), "name": bot_profile.get("name")}
    elif event.get("bot_id"):
        summary["bot"] = {"id": event.get("bot_id"), "name": None}
    return {key: value for key, value in summary.items() if value is not None}


__all__ = ["ALLOWED_POSTER_MODES", "handle_slack_message_for_loops", "slack_workspace_has_loop_triggers"]
