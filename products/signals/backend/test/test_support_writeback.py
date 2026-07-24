import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

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

    def test_posts_a_private_note_carrying_the_findings(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.fetch_implementation_pr_urls_for_reports", return_value={}):
            posted = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        assert posted == 1
        note = _ticket_notes(self.team, self.ticket).get()
        assert note.item_context["is_private"] is True
        assert note.item_context["author_type"] == "AI"
        assert "fix(widget): stop dropping replies" in note.content
        assert "localStorage id" in note.content
        assert f"/project/{self.team.pk}/inbox/{self.report.id}" in note.content

    def test_includes_the_implementation_pr_when_one_exists(self):
        pr_url = "https://github.com/PostHog/posthog/pull/73507"
        with patch(
            f"{WRITEBACK_MODULE_PATH}.fetch_implementation_pr_urls_for_reports",
            return_value={str(self.report.id): pr_url},
        ):
            post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        assert pr_url in _ticket_notes(self.team, self.ticket).get().content

    def test_is_idempotent_across_retries(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.fetch_implementation_pr_urls_for_reports", return_value={}):
            first = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])
            second = post_report_findings_to_tickets(self.team, str(self.report.id), [self.signal])

        assert (first, second) == (1, 0)
        assert _ticket_notes(self.team, self.ticket).count() == 1

    def test_ignores_signals_from_other_products(self):
        error_signal = {"source_product": "error_tracking", "source_id": "issue-1"}

        with patch(f"{WRITEBACK_MODULE_PATH}.fetch_implementation_pr_urls_for_reports", return_value={}):
            posted = post_report_findings_to_tickets(self.team, str(self.report.id), [error_signal])

        assert posted == 0
        assert not Comment.objects.filter(team=self.team, scope="conversations_ticket").exists()

    def test_does_not_leak_across_teams(self):
        other_team_signal = {"source_product": "conversations", "source_id": str(uuid.uuid4())}

        with patch(f"{WRITEBACK_MODULE_PATH}.fetch_implementation_pr_urls_for_reports", return_value={}):
            posted = post_report_findings_to_tickets(self.team, str(self.report.id), [other_team_signal])

        assert posted == 0
