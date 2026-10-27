"""Invitations to book a research interview with the Slack app team.

Every invitation links to ``BOOKING_URL``. A click arrives as a ``block_actions`` payload, which is
how the click is counted.

- The bad-rating modal always shows the link, because the reader already chose to tell us what went wrong.
- The Home tab shows a button when the ``slack-app-interview-recruitment`` flag selects the reader.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, get_args

from django.http import HttpResponse

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration

from products.slack_app.backend.analytics import capture_slack_event, slack_distinct_id
from products.slack_app.backend.feature_flags import is_slack_app_interview_recruitment_enabled
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

InterviewSurface = Literal["home", "bad_rating_modal"]
INTERVIEW_SURFACES: frozenset[str] = frozenset(get_args(InterviewSurface))

BOOKING_URL = "https://cal.com/vojta-bartos-wye08f/posthog-slack-app"
INVITE_MESSAGE = "Got 30 minutes to tell us how the PostHog Slack app works for you? Book a chat with the team."
MODAL_INVITE_MESSAGE = "Want to talk it through? Book 30 minutes with the team."

INTERVIEW_BOOK_ACTION_ID = "slack_app_interview:book"
INTERVIEW_ACTION_IDS: frozenset[str] = frozenset({INTERVIEW_BOOK_ACTION_ID})
_CLICK_EVENTS: dict[str, str] = {INTERVIEW_BOOK_ACTION_ID: "slack app interview invite clicked"}


def linked_posthog_user(integration: Integration, slack_user_id: str) -> User | None:
    """The PostHog user behind this Slack identity. Best-effort, because the result only targets the flag and labels events."""
    try:
        return find_linked_posthog_user(
            slack_user_id=slack_user_id,
            slack_team_id=integration.integration_id or "",
            candidate_org_ids={integration.team.organization_id},
        )
    except Exception:
        logger.warning("slack_app_interview_user_lookup_failed", integration_id=integration.id, exc_info=True)
        return None


def is_recruiting(integration: Integration, slack_user_id: str, posthog_user: User | None) -> bool:
    distinct_id = (
        posthog_user.distinct_id
        if posthog_user is not None and posthog_user.distinct_id
        else slack_distinct_id(integration, slack_user_id)
    )
    return is_slack_app_interview_recruitment_enabled(integration, distinct_id)


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
    """Record a click on an invitation's booking button.

    Slack opens the booking page itself and sends this payload only so the click can be counted.
    """
    clicked = _clicked(payload)
    slack_user_id = (payload.get("user") or {}).get("id")
    slack_team_id = (payload.get("team") or {}).get("id")
    integration_id = _integration_id(clicked)
    if clicked is None or integration_id is None or not slack_user_id or not slack_team_id:
        return HttpResponse(status=200)
    value = clicked.value
    integration = (
        Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind="slack",
            integration_id=slack_team_id,
        )
        .select_related("team__organization")
        .first()
    )
    surface = value.get("surface")
    if integration is None or surface not in INTERVIEW_SURFACES:
        return HttpResponse(status=200)

    capture_slack_event(
        integration,
        _CLICK_EVENTS[clicked.action_id],
        slack_user_id=slack_user_id,
        posthog_user=linked_posthog_user(integration, slack_user_id),
        surface=surface,
        task_run_id=value.get("run_id"),
        ai_trace_id=value.get("trace_id"),
    )
    return HttpResponse(status=200)
