from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.scoping import team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.slack.channels import post_with_join

from products.slack_app.backend.facade.api import slack_followup_invite_text

from ..facade.enums import SessionStatus
from ..models import ResearchSession
from .briefs import compose_brief, contact_checks_for
from .contact_check import check_contact
from .sessions import session_to_dto

logger = structlog.get_logger(__name__)

BRIEF_WINDOW = timedelta(hours=24)
MAX_BRIEFS_PER_RUN = 25
BRIEF_POSTED_EVENT = "research desk brief posted"
_INVITE_UTM_TAGS = "utm_source=posthog&utm_campaign=research_desk_brief&utm_medium=slack"


def _due_sessions(now: datetime) -> list[ResearchSession]:
    return list(
        ResearchSession.objects.filter(
            status=SessionStatus.SCHEDULED,
            brief_posted_at__isnull=True,
            start_time__gte=now,
            start_time__lt=now + BRIEF_WINDOW,
        ).order_by("start_time")[:MAX_BRIEFS_PER_RUN]
    )


def _claim(session_id: UUID, now: datetime) -> bool:
    # The conditional update runs on the writer, so of two overlapping runs only one wins the row,
    # even when the candidate list came from a lagging replica.
    return (
        ResearchSession.objects.filter(
            id=session_id, brief_posted_at__isnull=True, status=SessionStatus.SCHEDULED
        ).update(brief_posted_at=now)
        == 1
    )


def _release(session_id: UUID) -> None:
    ResearchSession.objects.filter(id=session_id, slack_message_ts="").update(brief_posted_at=None)


def post_due_briefs(now: datetime | None = None) -> int:
    """Post one Slack brief for each scheduled session that starts in the next 24 hours.

    Returns the number of briefs posted. Does nothing until the team, integration and channel are
    all configured.
    """
    team_id = settings.RESEARCH_DESK_TEAM_ID
    integration_id = settings.RESEARCH_DESK_SLACK_INTEGRATION_ID
    channel_id = settings.RESEARCH_DESK_SLACK_CHANNEL_ID
    if not (team_id and integration_id and channel_id):
        return 0

    integration = Integration.objects.filter(id=integration_id, team_id=team_id, kind="slack").first()
    if integration is None:
        logger.warning("research_desk_brief_integration_missing", integration_id=integration_id)
        return 0

    now = now or timezone.now()
    slack = SlackIntegration(integration, source="research_desk")
    invite = slack_followup_invite_text(
        integration, utm_tags=_INVITE_UTM_TAGS, ai_enabled=True, subject="this customer's account"
    )

    posted: list[UUID] = []
    with team_scope(team_id):
        for session in _due_sessions(now):
            if not _claim(session.id, now):
                continue
            dto = session_to_dto(session)
            try:
                checks = [check_contact(check) for check in contact_checks_for(dto, team_id)]
                brief = compose_brief(dto, checks, followup_invite=invite)
                ts = post_with_join(slack, channel_id, brief.blocks, brief.text)
            except Exception as e:
                # A failed post releases the claim so the next run retries it.
                _release(session.id)
                logger.exception("research_desk_brief_post_failed", session_id=str(session.id), error=str(e))
                continue
            ResearchSession.objects.filter(id=session.id).update(slack_message_ts=ts or "")
            posted.append(session.id)

    if posted:
        with ph_scoped_capture() as capture:
            for session_id in posted:
                capture(
                    distinct_id=f"research_desk_team_{team_id}",
                    event=BRIEF_POSTED_EVENT,
                    properties={"session_id": str(session_id), "team_id": team_id},
                )
    return len(posted)
