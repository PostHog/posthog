"""Support tickets assigned to the person. Metadata only, never message text."""

from products.conversations.backend.facade import api as conversations

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import Candidate, SourceContext, app_url

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# Tickets rank before error issues and GitHub inside the "other" group.
_SUBGROUP = 0


def collect(ctx: SourceContext) -> list[Candidate]:
    candidates = []
    for ticket in conversations.open_tickets_assigned_to_user(team_id=ctx.team.id, user_id=ctx.user.id):
        sla_at_risk = ticket.sla_due_at is not None and (ticket.sla_due_at - ctx.now).total_seconds() < 3600
        days_quiet = max((ctx.now - ticket.updated_at).days, 0)
        candidates.append(
            Candidate(
                key=f"ticket:{ticket.ticket_id}",
                group=ItemGroup.OTHER,
                source=ItemSource.SUPPORT,
                reason=ItemReason.ASSIGNED_TICKET,
                title=f"Support ticket #{ticket.ticket_number}",
                url=app_url(ctx.team.id, f"support/tickets/{ticket.ticket_id}"),
                sort_key=(
                    _SUBGROUP,
                    0 if sla_at_risk else 1,
                    -ticket.unread_team_count,
                    _PRIORITY_ORDER.get(ticket.priority or "", 4),
                    -days_quiet,
                ),
                facts={
                    "ticket_number": ticket.ticket_number,
                    "channel": ticket.channel_source,
                    "priority": ticket.priority,
                    "unread_messages": ticket.unread_team_count,
                    "messages": ticket.message_count,
                    "days_without_update": days_quiet,
                    "sla_at_risk_or_breached": sla_at_risk,
                },
            )
        )
    return candidates
