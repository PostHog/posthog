"""Invitations to book a research interview with the Slack app team.

The ``slack-app-interview-recruitment`` flag decides who gets an invitation. Each variant key is a
campaign id, and the variant's payload holds the message and the booking link. The flag targets
people, so a Slack user with no linked PostHog account matches only a rule that needs no person
property.

A person gets at most one unsolicited invitation in ``INVITE_INTERVAL``. The Home tab button does
not count, because the reader opens the tab and clicks by choice.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import HttpResponse
from django.utils import timezone

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from posthog.dataclasses import frozen
from posthog.models.integration import Integration

from products.slack_app.backend.analytics import capture_slack_event, slack_distinct_id
from products.slack_app.backend.feature_flags import get_slack_app_interview_recruitment_flag
from products.slack_app.backend.logic.feature_tips.state import FeatureTipsState, update_state
from products.slack_app.backend.services.slack_user_oauth import find_linked_posthog_user

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

InterviewSurface = Literal["home", "bad_rating_modal"]
INTERVIEW_SURFACES: frozenset[str] = frozenset({"home", "bad_rating_modal"})

DEFAULT_CAMPAIGN_ID = "slack-research"
INVITE_INTERVAL = timedelta(days=30)

INTERVIEW_BOOK_ACTION_ID = "slack_app_interview:book"
INTERVIEW_ACTION_IDS: frozenset[str] = frozenset({INTERVIEW_BOOK_ACTION_ID})


class _CampaignPayload(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    booking_url: str
    min_interactions: int = Field(default=3, ge=0, le=1000)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        return value.strip()

    @field_validator("booking_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError("booking_url must be an https URL")
        return value


@frozen
class InterviewCampaign:
    campaign_id: str
    message: str
    booking_url: str
    min_interactions: int


def parse_campaign(variant: Any, payload: Any) -> InterviewCampaign | None:
    """The campaign a flag result describes, or ``None`` when the payload cannot be used.

    A boolean rollout has no variant and runs the default campaign. The payload is typed by hand
    into the flag, so a bad value turns the invitation off instead of showing a broken link.
    """
    campaign_id = variant if isinstance(variant, str) and variant else DEFAULT_CAMPAIGN_ID
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    try:
        parsed = _CampaignPayload.model_validate(payload)
    except ValidationError:
        logger.warning("slack_app_interview_campaign_invalid", campaign_id=campaign_id)
        return None
    if not parsed.message:
        return None
    return InterviewCampaign(
        campaign_id=campaign_id,
        message=parsed.message,
        booking_url=parsed.booking_url,
        min_interactions=parsed.min_interactions,
    )


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


def resolve_campaign(
    integration: Integration, slack_user_id: str, posthog_user: User | None
) -> InterviewCampaign | None:
    distinct_id = (
        posthog_user.distinct_id
        if posthog_user is not None and posthog_user.distinct_id
        else slack_distinct_id(integration, slack_user_id)
    )
    result = get_slack_app_interview_recruitment_flag(integration, distinct_id)
    if result is None:
        return None
    return parse_campaign(result.variant, result.payload)


def booking_link(campaign: InterviewCampaign, surface: InterviewSurface, invitation_id: str) -> str:
    """The booking URL with the invitation's attribution in cal.com ``metadata`` parameters.

    cal.com copies these parameters into the booking webhook, which is how a booking joins the
    invitation that led to it. The link goes to a third party, so it carries no email or Slack id.
    """
    parts = urlsplit(campaign.booking_url)
    query = [
        *parse_qsl(parts.query, keep_blank_values=True),
        ("metadata[campaign_id]", campaign.campaign_id),
        ("metadata[surface]", surface),
        ("metadata[invitation_id]", invitation_id),
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def new_invitation_id() -> str:
    return str(uuid.uuid4())


def book_button(
    integration_id: int,
    campaign: InterviewCampaign,
    surface: InterviewSurface,
    invitation_id: str,
    **extra: str | None,
) -> dict[str, Any]:
    # The integration id lets the cross-region interactivity router find the region that owns the click.
    value = {
        "integration_id": integration_id,
        "campaign_id": campaign.campaign_id,
        "surface": surface,
        "invitation_id": invitation_id,
        **{key: item for key, item in extra.items() if item},
    }
    return {
        "type": "button",
        "action_id": INTERVIEW_BOOK_ACTION_ID,
        "text": {"type": "plain_text", "text": "Book a chat"},
        "style": "primary",
        "url": booking_link(campaign, surface, invitation_id),
        "value": json.dumps(value),
    }


def invite_section(text: str, button: dict[str, Any]) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}, "accessory": button}


def is_invite_due(state: FeatureTipsState, now: datetime) -> bool:
    return state.interview_invited_at is None or now - state.interview_invited_at >= INVITE_INTERVAL


def reserve_invite(slack_workspace_id: str, slack_user_id: str) -> bool:
    """Hold this person's invitation slot. ``False`` means another invitation is too recent.

    The slot is held before the invitation shows, so two answers that finish together cannot both
    send one. An invitation that then fails to show gives up the slot, which is the cheaper mistake.
    """
    now = timezone.now()
    reserved = False

    def change(state: FeatureTipsState) -> None:
        nonlocal reserved
        if is_invite_due(state, now):
            state.interview_invited_at = now
            reserved = True

    update_state(slack_workspace_id, slack_user_id, change)
    return reserved


def capture_invite_shown(
    integration: Integration,
    *,
    slack_user_id: str,
    posthog_user: User | None,
    campaign: InterviewCampaign,
    surface: InterviewSurface,
    invitation_id: str,
    **props: object,
) -> None:
    capture_slack_event(
        integration,
        "slack app interview invite shown",
        slack_user_id=slack_user_id,
        posthog_user=posthog_user,
        campaign_id=campaign.campaign_id,
        surface=surface,
        invitation_id=invitation_id,
        **props,
    )


def _clicked_value(payload: dict[str, Any]) -> dict[str, Any] | None:
    for action in payload.get("actions", []) or ():
        if action.get("action_id") not in INTERVIEW_ACTION_IDS:
            continue
        try:
            value = json.loads(action.get("value") or "")
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None


def is_interview_action(action_id: object) -> bool:
    return action_id in INTERVIEW_ACTION_IDS


def interview_integration_hint(payload: dict[str, Any]) -> int | None:
    value = _clicked_value(payload)
    integration_id = value.get("integration_id") if value else None
    return integration_id if isinstance(integration_id, int) else None


def handle_interview_action(payload: dict[str, Any]) -> HttpResponse:
    """Record a click on an invitation's booking button.

    Slack opens the booking page itself and sends this payload only so the click can be counted.
    """
    value = _clicked_value(payload)
    slack_user_id = (payload.get("user") or {}).get("id")
    slack_team_id = (payload.get("team") or {}).get("id")
    integration_id = value.get("integration_id") if value else None
    if value is None or not isinstance(integration_id, int) or not slack_user_id or not slack_team_id:
        return HttpResponse(status=200)
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
        "slack app interview invite clicked",
        slack_user_id=slack_user_id,
        posthog_user=linked_posthog_user(integration, slack_user_id),
        campaign_id=value.get("campaign_id"),
        surface=surface,
        invitation_id=value.get("invitation_id"),
        task_run_id=value.get("run_id"),
        ai_trace_id=value.get("trace_id"),
    )
    return HttpResponse(status=200)
