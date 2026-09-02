"""What a reader's rating of an agent answer becomes.

Rating is analytics only: it changes nothing about the run, and a reader who picks the
other rating later simply sends a second event. What a pick produces is the pair of
events AI observability already understands, ``$ai_metric`` for the rating and
``$ai_feedback`` for the reason, tagged with the same ``ai_product`` the run's own
generations carry so Slack feedback sits beside the web and desktop clients' rather than
in a surface of its own.

A rating arrives two ways: a click on the reply's thumbs, or a thumbs emoji reacted onto
the reply. Both become the same ``$ai_metric``, split by ``feedback_source``; only a
clicked thumbs-down can ask for a reason, because a reaction carries no ``trigger_id`` to
open a modal with.

Kept out of ``api.py`` so that module stays the interactivity/event router: it imports
the hint extractor for region ownership and the handler entrypoints.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from django.http import HttpResponse, JsonResponse

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.analytics import slack_event_props
from products.slack_app.backend.services.slack_messages import SLACK_WEBHOOK_TIMEOUT_SECONDS, TURN_FEEDBACK_ACTION_ID
from products.slack_app.backend.services.slack_user_info import get_cached_bot_user_id

logger = structlog.get_logger(__name__)

SLACK_INTEGRATION_KIND = "slack"

TURN_FEEDBACK_MODAL_CALLBACK_ID = "slack_app_turn_feedback_modal"
_MODAL_TEXT_BLOCK_ID = "feedback_text"
_MODAL_TEXT_ACTION_ID = "text"

# What the run's own generations are already tagged with, so a rating joins them: a
# Slack-origin run resolves to this gateway product (`_ORIGIN_TO_GATEWAY_PRODUCT` in
# `products/tasks/backend/temporal/process_task/ai_gateway_token.py`) and the gateway
# stamps it onto every `$ai_generation`. The other clients make the same match — desktop
# sends `posthog_code`, web sends `posthog_ai` — which is what puts all PostHog AI
# feedback on one metric, split by this property.
AI_PRODUCT = "slack_app"

# Slack's own cap on a `plain_text_input`, and Slack rejects the whole view past it, so the
# modal would not open at all. Below the desktop client's 4000 on purpose: a reason typed
# into this modal can never be longer, so one number serves the field and the truncation.
FEEDBACK_TEXT_MAX_LENGTH = 3000

_RATINGS: dict[str, Literal["good", "bad"]] = {"positive": "good", "negative": "bad"}

# Slack sends a reaction as its emoji name, with any skin tone appended after ``::``.
# ``+1``/``-1`` are the canonical names for the thumbs; ``thumbsup``/``thumbsdown`` are
# their standing aliases, kept here in case a client sends the alias form.
_REACTION_SENTIMENTS: dict[str, str] = {
    "+1": "positive",
    "thumbsup": "positive",
    "-1": "negative",
    "thumbsdown": "negative",
}

# The outcomes ``handle_reaction_added`` reports to the event router. ``not_local`` means
# the reacted reply belongs to an integration the other region owns, so the router should
# forward the event there.
ReactionOutcome = Literal["handled", "not_local"]
REACTION_HANDLED: ReactionOutcome = "handled"
REACTION_NOT_LOCAL: ReactionOutcome = "not_local"


@frozen
class _FeedbackTarget:
    """The run a rating is about, resolved against the workspace that owns it.

    Built only by ``_resolve_target`` on an integration ``_local_integration`` matched,
    which is what makes every field here trusted: the integration is matched on the Slack
    team the rating came from, and the run is looked up scoped to that integration's
    project, so a forged ``run_id`` resolves to nothing rather than attributing feedback
    to another team's run.
    """

    integration: Integration
    run_id: str
    task_id: str | None
    turn_id: str | None
    slack_user_id: str


def _parse_action_value(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def clicked_feedback_value(payload: dict) -> dict[str, Any]:
    """The thumb that was clicked, as its value. Empty when this click is not a rating.

    Slack sends back only the button the reader pressed, so the value alone says which
    thumb it was.
    """
    action = next(
        (a for a in payload.get("actions", []) or () if a.get("action_id") == TURN_FEEDBACK_ACTION_ID),
        None,
    )
    return _parse_action_value(action.get("value")) if action else {}


def _modal_metadata(payload: dict) -> dict[str, Any]:
    view = payload.get("view")
    if not isinstance(view, dict) or view.get("callback_id") != TURN_FEEDBACK_MODAL_CALLBACK_ID:
        return {}
    return _parse_action_value(view.get("private_metadata"))


def extract_modal_hint(payload: dict) -> int | None:
    """The integration id the reason modal carries, for region-ownership routing.

    Only the modal needs its own extractor. A clicked thumb carries the id in the
    button's ``value``, which the router's generic action-value hint already reads; a
    view submission carries no action at all, so the id rides in ``private_metadata``.
    """
    integration_id = _modal_metadata(payload).get("integration_id")
    return integration_id if isinstance(integration_id, int) else None


def _local_integration(integration_id: Any, slack_team_id: str | None) -> Integration | None:
    """The integration a rating names, if this region owns it for that Slack team.

    Scoped to the Slack team the rating came from, so a forged id resolves to nothing
    rather than crossing workspaces. ``None`` also covers an id whose row lives in the
    other region's database, which the reaction path forwards on.
    """
    if not slack_team_id or not isinstance(integration_id, int):
        return None
    return (
        Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        )
        # The event properties and the capture's groups both read through to the team and
        # its organization, and Slack gives the interaction three seconds.
        .select_related("team__organization")
        .first()
    )


def _resolve_target(
    value: dict[str, Any],
    *,
    integration: Integration,
    slack_user_id: str,
    turn_id: str | None,
) -> _FeedbackTarget | None:
    """Match the rating's run within ``integration``'s project, or answer ``None``.

    Anyone who can read the reply may rate it, so this is not an authorization check; the
    project scope is what keeps a rating from landing on a run the rater's workspace has
    nothing to do with.
    """
    # Deferred so the tasks product stays off this module's import path, matching
    # `slack_messages.load_run_footer`.
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415

    run_id = value.get("run_id")
    if not isinstance(run_id, str):
        return None
    try:
        UUID(run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    run = get_task_run(run_id, team_id=integration.team_id)
    if run is None:
        logger.info("slack_app_turn_feedback_unknown_run", integration_id=integration.id, run_id=run_id)
        return None

    return _FeedbackTarget(
        integration=integration,
        run_id=str(run.id),
        task_id=str(run.task_id),
        turn_id=turn_id,
        slack_user_id=slack_user_id,
    )


def _turn_id(payload: dict) -> str | None:
    """The rated answer's Slack timestamp, which is what identifies one turn in a thread.

    Stable for the life of the message, so a reader who changes their mind reports
    against the same turn and the later event is the one that counts.
    """
    message_ts = (payload.get("message") or {}).get("ts")
    if isinstance(message_ts, str) and message_ts:
        return message_ts
    container_ts = (payload.get("container") or {}).get("message_ts")
    return container_ts if isinstance(container_ts, str) and container_ts else None


def _distinct_id(target: _FeedbackTarget) -> str:
    """Who the feedback is attributed to.

    The PostHog user behind the Slack identity when there is one, so a rating joins that
    person's feedback from the web and desktop clients. An unlinked reader is attributed to
    the project instead of minting a person keyed on a Slack id; ``slack_user_id`` rides on
    the event either way, so the click is still traceable to someone we can follow up with.
    """
    from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user  # noqa: PLC0415

    try:
        user = find_linked_posthog_user(
            slack_user_id=target.slack_user_id,
            slack_team_id=target.integration.integration_id or "",
            candidate_org_ids={target.integration.team.organization_id},
        )
        if user is not None and user.distinct_id:
            return user.distinct_id
    except Exception:
        logger.warning("slack_app_turn_feedback_user_lookup_failed", integration_id=target.integration.id)
    return str(target.integration.team.uuid)


def _event_context(target: _FeedbackTarget) -> dict[str, Any]:
    """The properties both events share.

    The workspace half comes from ``slack_event_props``, the bundle every Slack app event
    carries, so a rating can be joined against the rest of them.

    ``$ai_session_id`` is the task id because every ``$ai_generation`` of a run carries it
    as ``task_id``, which is the same bargain the desktop client makes. ``$ai_trace_id`` is
    absent until the sandbox exposes per-turn trace ids; adding it here is what will attach
    a rating to the exact generation rather than to the run.
    """
    return slack_event_props(
        target.integration,
        slack_user_id=target.slack_user_id,
        **{
            "$ai_session_id": target.task_id,
            "ai_product": AI_PRODUCT,
            "agent_runtime": "sandbox",
            "task_id": target.task_id,
            "task_run_id": target.run_id,
            "turn_id": target.turn_id,
        },
    )


def _capture(target: _FeedbackTarget, event: str, properties: dict[str, Any]) -> None:
    """Send one feedback event. Best-effort: analytics never breaks the click."""
    try:
        team = target.integration.team
        posthoganalytics.capture(
            distinct_id=_distinct_id(target),
            event=event,
            properties={**_event_context(target), **properties},
            groups=groups(team.organization, team),
        )
    except Exception:
        # NB: structlog's first positional arg is named `event`, so the captured event
        # rides under a different key rather than colliding with it.
        logger.warning("slack_app_turn_feedback_capture_failed", captured_event=event, exc_info=True)


def _render_reason_modal(private_metadata: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": TURN_FEEDBACK_MODAL_CALLBACK_ID,
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Feedback"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": _MODAL_TEXT_BLOCK_ID,
                "label": {"type": "plain_text", "text": "What went wrong?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _MODAL_TEXT_ACTION_ID,
                    "multiline": True,
                    "max_length": FEEDBACK_TEXT_MAX_LENGTH,
                    "placeholder": {"type": "plain_text", "text": "What did you expect instead?"},
                },
            }
        ],
    }


def _open_reason_modal(payload: dict, target: _FeedbackTarget) -> None:
    """Ask a bad rating for its reason. Best-effort: the rating is already recorded."""
    trigger_id = payload.get("trigger_id")
    if not trigger_id:
        return
    private_metadata = json.dumps(
        {
            "integration_id": target.integration.id,
            "run_id": target.run_id,
            "turn_id": target.turn_id,
        }
    )
    try:
        SlackIntegration(target.integration).client.views_open(
            trigger_id=trigger_id, view=_render_reason_modal(private_metadata)
        )
    except Exception:
        logger.warning("slack_app_turn_feedback_modal_open_failed", run_id=target.run_id, exc_info=True)


def handle_turn_feedback_click(payload: dict) -> HttpResponse:
    """Record a clicked thumb, and ask a thumbs-down what went wrong.

    The reply is left as it is. A rating is one reader's view of an answer the whole
    thread can see, so rewriting the message would report it to everyone; the modal is
    what tells a thumbs-down that the click landed.
    """
    value = clicked_feedback_value(payload)
    sentiment = value.get("sentiment")
    rating = _RATINGS.get(sentiment) if isinstance(sentiment, str) else None
    if rating is None:
        logger.info("slack_app_turn_feedback_unknown_sentiment", sentiment=sentiment)
        return HttpResponse(status=200)

    integration = _local_integration(value.get("integration_id"), payload.get("team", {}).get("id"))
    target = (
        _resolve_target(
            value,
            integration=integration,
            slack_user_id=payload.get("user", {}).get("id", ""),
            turn_id=_turn_id(payload),
        )
        if integration
        else None
    )
    if target is None:
        return HttpResponse(status=200)

    # The modal goes first. Its trigger expires seconds after the click, while the capture
    # resolves the clicker's identity against the database on its way out.
    if sentiment == "negative":
        _open_reason_modal(payload, target)
    _capture(
        target,
        "$ai_metric",
        {"$ai_metric_name": "quality", "$ai_metric_value": rating, "feedback_source": "button"},
    )
    return HttpResponse(status=200)


def handle_turn_feedback_modal_submit(payload: dict) -> HttpResponse:
    """Record the reason typed into the bad-rating modal.

    The rating itself went out when the option was picked, so an abandoned modal costs
    nothing: this only adds the text.
    """
    metadata = _modal_metadata(payload)
    if not metadata:
        return HttpResponse(status=200)

    values = payload.get("view", {}).get("state", {}).get("values", {})
    raw_text = values.get(_MODAL_TEXT_BLOCK_ID, {}).get(_MODAL_TEXT_ACTION_ID, {}).get("value") or ""
    text = raw_text.strip()[:FEEDBACK_TEXT_MAX_LENGTH]
    if not text:
        # A submission error keeps the modal open with the message under the field.
        return JsonResponse({"response_action": "errors", "errors": {_MODAL_TEXT_BLOCK_ID: "Tell us what went wrong."}})

    turn_id = metadata.get("turn_id")
    integration = _local_integration(metadata.get("integration_id"), payload.get("team", {}).get("id"))
    target = (
        _resolve_target(
            metadata,
            integration=integration,
            slack_user_id=payload.get("user", {}).get("id", ""),
            turn_id=turn_id if isinstance(turn_id, str) else None,
        )
        if integration
        else None
    )
    if target is None:
        return HttpResponse(status=200)

    _capture(
        target,
        "$ai_feedback",
        {"$ai_feedback_text": text, "feedback_type": "bad", "feedback_source": "button"},
    )
    return HttpResponse(status=200)


def reaction_sentiment(reaction: Any) -> str | None:
    """The rating a reaction stands for, or ``None`` for any other emoji.

    A skin-toned thumb arrives as ``+1::skin-tone-3``; the tone changes nothing about the
    rating, so only the base name is matched.
    """
    if not isinstance(reaction, str):
        return None
    return _REACTION_SENTIMENTS.get(reaction.split("::", 1)[0])


def _fetch_reacted_message(workspace_integration: Integration, channel: str, message_ts: str) -> dict[str, Any] | None:
    """The reacted message, read back from Slack so its blocks can say which run it is.

    ``conversations.replies`` accepts the ts of any message in a thread, and agent replies
    always live in threads.
    """
    try:
        client = SlackIntegration(workspace_integration).client
        client.timeout = SLACK_WEBHOOK_TIMEOUT_SECONDS
        response = client.conversations_replies(
            channel=channel, ts=message_ts, latest=message_ts, inclusive=True, limit=1
        )
        messages = response.get("messages") or []
    except Exception:
        logger.warning(
            "slack_app_reaction_feedback_fetch_failed",
            integration_id=workspace_integration.id,
            channel=channel,
            message_ts=message_ts,
            exc_info=True,
        )
        return None
    return next((m for m in messages if isinstance(m, dict) and m.get("ts") == message_ts), None)


def _feedback_value_from_message(message: dict[str, Any]) -> dict[str, Any]:
    """The thumbs' target, read off the reacted reply's own blocks.

    Only agent replies carry the feedback element, so finding it is also the gate: a
    reaction on any other bot message resolves to nothing. Both buttons carry the same
    integration and run, so either value serves.
    """
    for block in message.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        for element in block.get("elements") or []:
            if isinstance(element, dict) and element.get("action_id") == TURN_FEEDBACK_ACTION_ID:
                return _parse_action_value((element.get("positive_button") or {}).get("value"))
    return {}


def handle_reaction_added(event: dict, slack_team_id: str, workspace_integration: Integration) -> ReactionOutcome:
    """Record a thumbs reaction on an agent reply as a rating.

    ``workspace_integration`` is any of this region's integrations for the Slack team; its
    token is what reads the reacted message back. The reply's own button value then names
    the integration the run belongs to, and ``REACTION_NOT_LOCAL`` reports that row living
    in the other region so the event router can forward the event there. Everything this
    handler ignores, including reactions that are not a thumb, is ``REACTION_HANDLED``.
    """
    sentiment = reaction_sentiment(event.get("reaction"))
    rating = _RATINGS.get(sentiment) if sentiment else None
    item = event.get("item") or {}
    channel = item.get("channel")
    message_ts = item.get("ts")
    if (
        rating is None
        or item.get("type") != "message"
        or not isinstance(channel, str)
        or not isinstance(message_ts, str)
    ):
        return REACTION_HANDLED

    # Most thumbs in a channel land on human messages; the author check keeps those from
    # each costing a Slack fetch. `get_cached_bot_user_id` settles a cold cache itself, so
    # `None` means the token is broken or Slack is failing. A rating is best-effort
    # analytics, so skip it then rather than pay a doomed fetch per reaction.
    bot_user_id = get_cached_bot_user_id(SlackIntegration(workspace_integration), workspace_integration)
    if bot_user_id is None or event.get("item_user") != bot_user_id:
        return REACTION_HANDLED

    message = _fetch_reacted_message(workspace_integration, channel, message_ts)
    value = _feedback_value_from_message(message) if message else {}
    if not isinstance(value.get("integration_id"), int):
        return REACTION_HANDLED

    integration = _local_integration(value.get("integration_id"), slack_team_id)
    if integration is None:
        return REACTION_NOT_LOCAL

    target = _resolve_target(
        value,
        integration=integration,
        slack_user_id=str(event.get("user") or ""),
        turn_id=message_ts,
    )
    if target is None:
        return REACTION_HANDLED

    _capture(
        target,
        "$ai_metric",
        {
            "$ai_metric_name": "quality",
            "$ai_metric_value": rating,
            "feedback_source": "reaction",
            "reaction": event.get("reaction"),
        },
    )
    return REACTION_HANDLED
