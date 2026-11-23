"""Invitations to book a research interview with the Slack app team.

Every invitation links to ``BOOKING_URL``. A click arrives as a ``block_actions`` payload, which is
how the click is counted.

Three surfaces show an invitation:

- The bad-rating modal always shows the link, because the reader already chose to tell us what went wrong.
- The Home tab always shows a button.
- A private message under the answer offers the interview when the reader shows frustration: a thumbs-down reaction on an answer, or a message that the decision model
  reads as unhappy with the assistant or PostHog. A reader gets at most one such message in ``INVITE_INTERVAL``, and
  "Don't ask again" stops these messages only. The model runs only after every cheap gate passes, so
  most answers cost no call.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, get_args

from django.http import HttpResponse
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.feature_tips.state import FeatureTipsState, get_state, update_state
from products.slack_app.backend.logic.message_sentiment import is_unhappy
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.slack_messages import post_slack_ephemeral, section_block
from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, get_workspace_integration

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

InterviewSurface = Literal["home", "bad_rating_modal", "frustration"]
INTERVIEW_SURFACES: frozenset[str] = frozenset(get_args(InterviewSurface))
FrustrationSignal = Literal["message", "reaction"]

BOOKING_URL = "https://cal.com/vojta-bartos-wye08f/posthog-slack-app"
INVITE_MESSAGE = "Got 30 minutes to tell us how the PostHog Slack app works for you? Book a chat with the team."
MODAL_INVITE_MESSAGE = "Want to talk it through? Book 30 minutes with the team."
# A first-time reader gets answers before any invitation, like the feature tips.
MIN_INTERACTIONS = 3
INVITE_INTERVAL = timedelta(days=30)
# A tip this recent probably sits under the answer the reader just reacted to.
TIP_GAP = timedelta(hours=1)

INTERVIEW_BOOK_ACTION_ID = "slack_app_interview:book"
INTERVIEW_DISMISS_ACTION_ID = "slack_app_interview:dismiss"
INTERVIEW_OPT_OUT_ACTION_ID = "slack_app_interview:opt_out"
INTERVIEW_ACTION_IDS: frozenset[str] = frozenset(
    {INTERVIEW_BOOK_ACTION_ID, INTERVIEW_DISMISS_ACTION_ID, INTERVIEW_OPT_OUT_ACTION_ID}
)
_CLICK_EVENTS: dict[str, str] = {
    INTERVIEW_BOOK_ACTION_ID: "slack app interview invite clicked",
    INTERVIEW_DISMISS_ACTION_ID: "slack app interview invite dismissed",
    INTERVIEW_OPT_OUT_ACTION_ID: "slack app interview invites turned off",
}
INVITES_OFF_TEXT = "👋 Got it. I won't ask you again."


def linked_posthog_user(integration: WorkspaceIntegration, slack_user_id: str) -> User | None:
    """The PostHog user behind this Slack identity. Best-effort, because the result only labels events and model calls."""
    try:
        return find_linked_posthog_user(
            slack_user_id=slack_user_id,
            slack_team_id=integration.integration_id or "",
            candidate_org_ids={integration.team.organization_id},
        )
    except Exception:
        logger.warning("slack_app_interview_user_lookup_failed", integration_id=integration.id, exc_info=True)
        return None


def book_button(integration_id: int, surface: InterviewSurface, **extra: str | None) -> dict[str, Any]:
    # The integration id lets the cross-region interactivity router find the region that owns the click.
    value = {"integration_id": integration_id, "surface": surface, **{key: item for key, item in extra.items() if item}}
    return {
        "type": "button",
        "action_id": INTERVIEW_BOOK_ACTION_ID,
        "text": {"type": "plain_text", "text": "Book a chat"},
        "style": "primary",
        "url": BOOKING_URL,
        "value": json.dumps(value),
    }


def invite_section(text: str, button: dict[str, Any]) -> dict[str, Any]:
    return {**section_block(text), "accessory": button}


@frozen
class FrustrationInviteRequest:
    integration: WorkspaceIntegration
    slack_user_id: str
    posthog_user: User | None
    channel: str
    thread_ts: str
    signal: FrustrationSignal
    person_message: str | None = None
    trace_id: str | None = None
    # A verdict the caller already has for ``person_message``, so the model does not run twice.
    unhappy: bool | None = None


def offer_frustration_invite(request: FrustrationInviteRequest) -> bool:
    """Post a private invitation under the answer when the reader shows frustration.

    ``True`` means the invitation posted, so the caller sends no feature tip under the same answer.
    """
    integration = request.integration
    workspace_id = integration.integration_id or ""
    state = get_state(workspace_id, request.slack_user_id)
    now = timezone.now()
    # A reader who turned feature tips off asked for fewer prompts, so this prompt stays away too.
    if state.opted_out_at is not None or not _is_invite_due(state):
        return False
    # A reaction arrives after the answer, so a tip may already sit under that answer. No answer gets two prompts.
    if state.last_shown_at is not None and now - state.last_shown_at < TIP_GAP:
        return False
    # The limit stops the count at the threshold, so a reader with a long history costs no full scan.
    thread_count = (
        SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=workspace_id, mentioning_slack_user_id=request.slack_user_id
        )
        .values("id")[:MIN_INTERACTIONS]
        .count()
    )
    if thread_count < MIN_INTERACTIONS:
        return False
    # Deferred like the other ee imports in this product, so ee stays off the import path of every caller.
    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    if request.signal == "message" and not (
        request.unhappy
        if request.unhappy is not None
        else is_unhappy(
            request.person_message or "",
            team_id=integration.team_id,
            distinct_id=request.posthog_user.distinct_id if request.posthog_user is not None else None,
            trace_id=request.trace_id,
            privacy_mode=is_privacy_mode_enabled(integration.team),
        )
    ):
        return False

    # The slot is held before the post, so two answers that finish together cannot both send one.
    reserved_at = _reserve_invite(workspace_id, request.slack_user_id)
    if reserved_at is None:
        return False
    invitation_id = str(uuid.uuid4())
    try:
        post_slack_ephemeral(
            SlackIntegration(integration).client,
            channel=request.channel,
            user=request.slack_user_id,
            thread_ts=request.thread_ts,
            text=INVITE_MESSAGE,
            blocks=frustration_invite_blocks(integration.id, invitation_id, request.trace_id),
        )
    except Exception:
        # The reader saw nothing, so the slot goes back.
        logger.warning("slack_app_interview_invite_post_failed", exc_info=True)
        _release_invite(workspace_id, request.slack_user_id, reserved_at)
        return False
    capture_slack_event(
        integration,
        "slack app interview invite shown",
        slack_user_id=request.slack_user_id,
        posthog_user=request.posthog_user,
        surface="frustration",
        invitation_id=invitation_id,
        signal=request.signal,
        ai_trace_id=request.trace_id,
    )
    return True


def _is_invite_due(state: FeatureTipsState) -> bool:
    if state.interview_opted_out_at is not None:
        return False
    return state.interview_invited_at is None or timezone.now() - state.interview_invited_at >= INVITE_INTERVAL


def _reserve_invite(slack_workspace_id: str, slack_user_id: str) -> datetime | None:
    """Hold this person's invitation slot, and return when. ``None`` means another invitation is too recent."""
    now = timezone.now()

    def change(state: FeatureTipsState) -> None:
        if _is_invite_due(state):
            state.interview_invited_at = now

    state = update_state(slack_workspace_id, slack_user_id, change)
    return now if state.interview_invited_at == now else None


def _release_invite(slack_workspace_id: str, slack_user_id: str, reserved_at: datetime) -> None:
    """Give back a slot that ``_reserve_invite`` held for an invitation the reader never saw."""

    def change(state: FeatureTipsState) -> None:
        # A later reservation is another invitation's slot, so only this one goes back.
        if state.interview_invited_at == reserved_at:
            state.interview_invited_at = None

    try:
        update_state(slack_workspace_id, slack_user_id, change)
    except Exception:
        logger.warning("slack_app_interview_invite_release_failed", exc_info=True)


def frustration_invite_blocks(integration_id: int, invitation_id: str, trace_id: str | None) -> list[dict[str, Any]]:
    book = book_button(integration_id, "frustration", invitation_id=invitation_id, trace_id=trace_id)

    def button(action_id: str, label: str) -> dict[str, Any]:
        return {
            "type": "button",
            "action_id": action_id,
            "text": {"type": "plain_text", "text": label},
            "value": book["value"],
        }

    return [
        section_block(INVITE_MESSAGE),
        {
            "type": "actions",
            "elements": [
                book,
                button(INTERVIEW_DISMISS_ACTION_ID, "Not now"),
                button(INTERVIEW_OPT_OUT_ACTION_ID, "Don't ask again"),
            ],
        },
    ]


@frozen
class _InterviewClick:
    action_id: str
    value: dict[str, Any]


def _clicked(payload: dict[str, Any]) -> _InterviewClick | None:
    for action in payload.get("actions", []) or ():
        action_id = action.get("action_id")
        if not is_interview_action(action_id):
            continue
        try:
            value = json.loads(action.get("value") or "")
        except json.JSONDecodeError:
            return None
        return _InterviewClick(action_id=action_id, value=value) if isinstance(value, dict) else None
    return None


def is_interview_action(action_id: object) -> bool:
    return action_id in INTERVIEW_ACTION_IDS


def _integration_id(clicked: _InterviewClick | None) -> int | None:
    integration_id = clicked.value.get("integration_id") if clicked is not None else None
    return integration_id if isinstance(integration_id, int) else None


def interview_integration_hint(payload: dict[str, Any]) -> int | None:
    return _integration_id(_clicked(payload))


def handle_interview_action(payload: dict[str, Any]) -> HttpResponse:
    """Record a click on an invitation's buttons.

    For the booking button, Slack opens the booking page itself and sends this payload only so the
    click can be counted. The private message goes away after any click, because it did its job.
    """
    clicked = _clicked(payload)
    slack_user_id = (payload.get("user") or {}).get("id")
    slack_team_id = (payload.get("team") or {}).get("id")
    integration_id = _integration_id(clicked)
    if clicked is None or integration_id is None or not slack_user_id or not slack_team_id:
        return HttpResponse(status=200)
    value = clicked.value
    integration = get_workspace_integration(integration_id, slack_team_id)
    surface = value.get("surface")
    if integration is None or surface not in INTERVIEW_SURFACES:
        return HttpResponse(status=200)

    response_url = payload.get("response_url") or ""
    if clicked.action_id == INTERVIEW_OPT_OUT_ACTION_ID:

        def change(state: FeatureTipsState) -> None:
            state.interview_opted_out_at = timezone.now()

        update_state(integration.integration_id or "", slack_user_id, change)
        post_response_url(response_url, {"replace_original": True, "text": INVITES_OFF_TEXT})
    elif response_url and (payload.get("container") or {}).get("is_ephemeral"):
        post_response_url(response_url, {"delete_original": True})

    capture_slack_event(
        integration,
        _CLICK_EVENTS[clicked.action_id],
        slack_user_id=slack_user_id,
        posthog_user=linked_posthog_user(integration, slack_user_id),
        surface=surface,
        invitation_id=value.get("invitation_id"),
        task_run_id=value.get("run_id"),
        ai_trace_id=value.get("trace_id"),
    )
    return HttpResponse(status=200)
