import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.comment import Comment

from products.conversations.backend.models import ConversationDelivery, TeamConversationsSlackConfig, Ticket
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport
from products.signals.backend.pull_requests import PullRequestStateSource, link_pull_request
from products.signals.backend.report_assignments import PullRequestDetails
from products.signals.backend.support_writeback import post_pull_request_to_tickets, post_report_findings_to_tickets
from products.tasks.backend.models import Task

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
        assert f"/project/{self.team.pk}/inbox/reports/{self.report.id}?link_source=support" in note.content

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

    def test_pull_request_note_is_private_and_idempotent(self):
        pr_url = "https://github.com/PostHog/posthog/pull/123"

        first = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [self.signal])
        second = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [self.signal])

        assert (first, second) == (1, 0)
        note = _ticket_notes(self.team, self.ticket).get()
        assert note.item_context["is_private"] is True
        assert note.item_context["author_type"] == "AI"
        assert pr_url in note.content
        assert f"/project/{self.team.pk}/inbox/reports/{self.report.id}?link_source=support" in note.content
        assert self.report.summary not in note.content

    def test_pull_request_reply_returns_to_the_slack_thread(self):
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team, defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"}
        )
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="slack-user",
            channel_source="slack",
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )
        signal = {"source_product": "conversations", "source_id": str(ticket.id)}
        pr_url = "https://github.com/PostHog/posthog/pull/123"

        first = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [signal])
        second = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [signal])

        assert (first, second) == (1, 0)
        reply = _ticket_notes(self.team, ticket).get()
        assert reply.item_context["is_private"] is False
        assert reply.content.startswith("[PostHog bot]")
        assert pr_url in reply.content
        assert str(self.report.id) not in reply.content
        delivery = ConversationDelivery.objects.for_team(self.team.id).get(comment_id=reply.id)
        assert delivery.route == {"channel": "C123", "thread_ts": "1700000000.000100"}

    def test_linking_pull_request_queues_ticket_note_once(self):
        pr_url = "https://github.com/PostHog/posthog/pull/123"
        task = Task.objects.create(team=self.team, created_by=self.user)
        details = PullRequestDetails(
            url=pr_url, repository="PostHog/posthog", number=123, state="unknown", merged=False
        )

        with patch("products.signals.backend.tasks.write_pull_request_to_support_tickets.delay") as send_note:
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(2):
                    link_pull_request(
                        report=self.report,
                        details=details,
                        actor=ArtefactAttribution.from_task(str(task.id)),
                        claim_id=None,
                        state_source=PullRequestStateSource.TASK_OUTPUT,
                        notify_reviewers=False,
                    )
                link_pull_request(
                    report=self.report,
                    details=PullRequestDetails(
                        url="https://github.com/PostHog/posthog/pull/124",
                        repository="PostHog/posthog",
                        number=124,
                        state="unknown",
                        merged=False,
                    ),
                    actor=ArtefactAttribution.from_user(self.user.id),
                    claim_id=None,
                    state_source=PullRequestStateSource.GITHUB,
                    notify_reviewers=False,
                )

        send_note.assert_called_once_with(self.team.pk, str(self.report.id), pr_url)

    def test_ignores_signals_from_other_products(self):
        error_signal = {"source_product": "error_tracking", "source_id": "issue-1"}

        posted = post_report_findings_to_tickets(self.team, str(self.report.id), [error_signal])

        assert posted == 0
        assert not Comment.objects.filter(team=self.team, scope="conversations_ticket").exists()

    def test_does_not_leak_across_teams(self):
        other_team_signal = {"source_product": "conversations", "source_id": str(uuid.uuid4())}

        posted = post_report_findings_to_tickets(self.team, str(self.report.id), [other_team_signal])

        assert posted == 0
