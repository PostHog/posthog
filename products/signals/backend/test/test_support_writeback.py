import uuid

import pytest
from posthog.test.base import BaseTest

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.signals.backend.models import SignalReport
from products.signals.backend.support_writeback import post_report_findings_to_tickets

WRITEBACK_MODULE_PATH = "products.signals.backend.support_writeback"


def _make_ticket(team):
    return Ticket.objects.create_with_number(
        team=team,
        widget_session_id=str(uuid.uuid4()),
        distinct_id="user-123",
        channel_source="widget",
    )


def _ticket_notes(team, ticket):
    return Comment.objects.filter(team=team, scope="conversations_ticket", item_id=str(ticket.id), deleted=False)


@pytest.mark.django_db
class TestPostReportFindingsToTickets(BaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = _make_ticket(self.team)
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="fix(widget): stop dropping replies",
            summary="The widget gates replies on a localStorage id.",
        )
        self.signal = {
            "source_product": "conversations",
            "source_id": str(self.ticket.id),
            "content": "customer can't see replies",
        }

    def test_posts_a_private_note_pointing_at_the_report(self):
        posted = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        assert posted == 1
        note = _ticket_notes(self.team, self.ticket).get()
        assert note.item_context["is_private"] is True
        assert note.item_context["author_type"] == "AI"
        assert f"/project/{self.team.pk}/inbox/{self.report.id}" in note.content

    def test_note_carries_no_report_content(self):
        # Comments authorize as `comment` while reports authorize as `task`, so a teammate with ticket
        # access but no inbox access can read this note. It must not hand them the research itself.
        post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        content = _ticket_notes(self.team, self.ticket).get().content
        assert self.report.title not in content
        assert "localStorage id" not in content

    def test_is_idempotent_across_retries(self):
        first = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])
        second = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        assert (first, second) == (1, 0)
        assert _ticket_notes(self.team, self.ticket).count() == 1

    def test_ignores_signals_from_other_products(self):
        error_signal = {"source_product": "error_tracking", "source_id": "issue-1"}

        posted = post_report_findings_to_tickets(self.team, str(self.report.id), [error_signal])

        assert posted == 0
        assert not Comment.objects.filter(team=self.team, scope="conversations_ticket").exists()

    def test_does_not_leak_across_teams(self):
        other_team_signal = {"source_product": "conversations", "source_id": str(uuid.uuid4())}

        posted = post_report_findings_to_tickets(self.team, str(self.report.id), [other_team_signal])

        assert posted == 0
