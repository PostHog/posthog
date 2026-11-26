from posthog.models.team import Team
from posthog.models.user import User

from products.growth.backend import posthog_support
from products.growth.backend.facade.posthog_support_types import (
    DraftedVia,
    DraftRefusal,
    FilingReason,
    SendFailure,
    SentSupportTicketResult,
    SupportDraft,
    TicketTopic,
)

# Callers must already have checked that the user may act in the team and applied the feature flag (and,
# for drafts, the draft throttle), as the viewset does.


class SupportDraftRefused(Exception):
    def __init__(self, refusal: DraftRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


class SupportTicketSendFailed(Exception):
    def __init__(
        self, failure: SendFailure, topic: TicketTopic | None = None, filing_reason: FilingReason | None = None
    ) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.topic = topic
        self.filing_reason = filing_reason


def compose_ticket_message(
    *,
    title: str,
    request: str,
    details: str | None = None,
    already_checked: str | None = None,
    error: str | None = None,
) -> str:
    return posthog_support.compose_ticket_message(
        title=title, request=request, details=details, already_checked=already_checked, error=error
    )


def draft_support_ticket(
    *,
    user_id: int,
    team_id: int,
    message: str,
    topic: TicketTopic,
    filing_reason: FilingReason,
    drafted_via: DraftedVia,
    mcp_session_id: str | None,
    mcp_conversation_id: str | None,
) -> SupportDraft:
    team = Team.objects.select_related("organization").get(pk=team_id)
    outcome = posthog_support.create_draft(
        User.objects.get(pk=user_id),
        team,
        message=message,
        topic=topic,
        filing_reason=filing_reason,
        drafted_via=drafted_via,
        mcp_session_id=mcp_session_id,
        mcp_conversation_id=mcp_conversation_id,
    )
    if outcome.refusal is not None:
        raise SupportDraftRefused(outcome.refusal)
    draft = outcome.draft
    assert draft is not None
    return SupportDraft(
        id=draft.id,
        message=draft.message,
        ticket_context=draft.ticket_context(team),
        expires_at=draft.expires_at,
        topic=draft.topic,
        filing_reason=draft.filing_reason,
        permission=outcome.permission,
    )


def send_support_ticket(*, user_id: int, team_id: int, draft_id: str) -> SentSupportTicketResult:
    outcome = posthog_support.send_draft(
        User.objects.get(pk=user_id), Team.objects.select_related("organization").get(pk=team_id), draft_id
    )
    draft = outcome.draft
    topic = draft.topic if draft else None
    filing_reason = draft.filing_reason if draft else None
    if outcome.failure is not None:
        raise SupportTicketSendFailed(outcome.failure, topic, filing_reason)
    assert outcome.ticket is not None
    return SentSupportTicketResult(
        ticket_id=outcome.ticket.ticket_id, newly_sent=not outcome.replayed, topic=topic, filing_reason=filing_reason
    )
