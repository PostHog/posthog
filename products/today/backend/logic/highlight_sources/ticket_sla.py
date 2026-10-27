from datetime import timedelta

from django.utils import timezone

from products.conversations.backend.facade.api import list_role_sla_breaches
from products.conversations.backend.facade.types import RoleSlaBreach

from ...facade.enums import HighlightLabel
from ..highlight_types import Candidate, Context, Found, Source

WINDOW = timedelta(hours=24)
# Relevance is 1 because the ticket is assigned to the viewer's role, so the score
# equals this importance and the item lands as P1.
IMPORTANCE = 0.8

ONE_TITLE = "Ticket #{number} assigned to {role} breaches its SLA within 24 hours"
MANY_TITLE = "{count} tickets assigned to {role} breach their SLA within 24 hours"
ONE_DETAIL = "Open it and reply before the deadline."
MANY_DETAIL = "Ticket #{number} is the soonest."
OPEN_STATUSES = ("new", "open", "pending", "on_hold")


def find(context: Context) -> Found:
    now = timezone.now()
    breaches = list_role_sla_breaches(context.team.id, context.user.id, due_after=now, due_before=now + WINDOW)
    return Found(items=tuple(_candidate(breach) for breach in breaches))


def _candidate(breach: RoleSlaBreach) -> Candidate:
    number = breach.soonest_ticket_number
    role = breach.role_name
    one = breach.ticket_count == 1
    statuses = "&".join(f"status={status}" for status in OPEN_STATUSES)
    return Candidate(
        key=f"ticket_sla:{breach.role_id}",
        label=HighlightLabel.RISK,
        family="support",
        importance=IMPORTANCE,
        relevance=1.0,
        title=(ONE_TITLE if one else MANY_TITLE).format(number=number, role=role, count=breach.ticket_count),
        detail=ONE_DETAIL if one else MANY_DETAIL.format(number=number),
        url=(
            f"/support/tickets/{number}"
            if one
            else f"/support/tickets?assignee=role:{breach.role_id}&{statuses}&order_by=sla_due_at"
        ),
        ref=f"role:{breach.role_id}",
    )


SOURCE = Source(name="ticket_sla", find=find, scopes=("ticket:read",))
