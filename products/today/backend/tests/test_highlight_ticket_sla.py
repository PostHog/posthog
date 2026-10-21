from datetime import UTC, date, datetime
from uuid import UUID

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.conversations.backend.facade.types import RoleSlaBreach
from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import ticket_sla
from products.today.backend.logic.highlight_types import Context

ROLE_ID = UUID("11111111-1111-1111-1111-111111111111")


class TestTicketSlaHighlight(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "one ticket names that ticket and opens it",
                1,
                "Ticket #12 assigned to Support breaches its SLA within 24 hours",
                "Open it and reply before the deadline.",
                "/support/tickets/12",
            ),
            (
                "several tickets name the count and open the role queue",
                3,
                "3 tickets assigned to Support breach their SLA within 24 hours",
                "Ticket #12 is the soonest.",
                f"/support/tickets?assignee=role:{ROLE_ID}&status=new&status=open&status=pending&status=on_hold&order_by=sla_due_at",
            ),
        ]
    )
    def test_a_role_breach_is_one_risk_item(self, _name: str, count: int, title: str, detail: str, url: str) -> None:
        breach = RoleSlaBreach(
            role_id=ROLE_ID,
            role_name="Support",
            ticket_count=count,
            soonest_ticket_number=12,
            soonest_due_at=datetime(2026, 10, 15, 14, 0, tzinfo=UTC),
        )
        registered = next(source for source in load_sources() if source.name == "ticket_sla")
        with patch("products.today.backend.logic.highlight_types.property_restrictions", return_value="0"):
            context = Context(Team(id=1), User(id=2), date(2026, 10, 15))

        with patch.object(ticket_sla, "list_role_sla_breaches", return_value=[breach]):
            found = registered.find(context)

        assert len(found.items) == 1
        item = found.items[0]
        assert item.title == title
        assert item.detail == detail
        assert item.label == HighlightLabel.RISK
        assert item.family == "support"
        assert item.importance == 0.8
        assert item.relevance == 1.0
        assert item.url == url
        assert registered.scopes == ("ticket:read",)
