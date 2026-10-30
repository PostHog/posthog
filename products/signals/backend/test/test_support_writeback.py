import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.facade import api as conversations_facade
from products.conversations.backend.models import ConversationDelivery, TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import TicketMessageType
from products.conversations.backend.services.messages import ticket_message_type
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.pull_requests import PullRequestStateSource, link_pull_request
from products.signals.backend.report_assignments import PullRequestDetails
from products.signals.backend.support_writeback import post_pull_request_to_tickets, post_report_findings_to_tickets
from products.tasks.backend.models import Task, TaskRun

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

    @parameterized.expand([("first", 1), ("second", 2)])
    def test_pull_request_note_failure_retries_without_duplicate_notes(self, _name, failing_call):
        other_ticket = _make_ticket(self.team)
        signals = [self.signal, {"source_product": "conversations", "source_id": str(other_ticket.id)}]
        pr_url = "https://github.com/PostHog/posthog/pull/123"
        original_post = conversations_facade.post_ticket_automated_update
        calls = 0

        def fail_once(**kwargs):
            nonlocal calls
            calls += 1
            if calls == failing_call:
                raise ConnectionError("temporary write failure")
            return original_post(**kwargs)

        with patch(f"{WRITEBACK_MODULE_PATH}.conversations_facade.post_ticket_automated_update", side_effect=fail_once):
            with pytest.raises(ConnectionError, match="temporary write failure"):
                post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, signals)
            post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, signals)

        assert _ticket_notes(self.team, self.ticket).count() == 1
        assert _ticket_notes(self.team, other_ticket).count() == 1
        assert calls == 4

    @parameterized.expand(
        [
            ("approved_internal", {"is_channel": True}, True, True),
            ("not_approved", {"is_channel": True}, False, False),
            ("shared", {"is_channel": True, "is_ext_shared": True}, True, False),
            ("unknown", {}, True, False),
            ("unreadable", None, True, False),
        ]
    )
    def test_pull_request_reply_only_enters_an_approved_internal_slack_thread(
        self, _name, channel_info, approved, expected_public
    ):
        self.team.conversations_settings = {"automated_update_slack_channel_ids": ["C123"] if approved else []}
        self.team.save(update_fields=["conversations_settings"])
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
        pr_url = "https://github.com/Post<@U123>Hog/posthog/pull/123?text=<@here>"
        client = MagicMock()
        if channel_info is None:
            client.conversations_info.side_effect = ConnectionError("Slack unavailable")
        else:
            client.conversations_info.return_value = {"channel": channel_info}

        with patch("products.conversations.backend.facade.api.get_slack_client", return_value=client):
            first = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [signal])
            second = post_pull_request_to_tickets(self.team, str(self.report.id), pr_url, [signal])

        if not approved:
            client.conversations_info.assert_not_called()

        assert (first, second) == (1, 0)
        reply = _ticket_notes(self.team, ticket).get()
        assert reply.item_context["is_private"] is not expected_public
        assert reply.content.startswith("[PostHog bot]")
        assert "https://github.com/Post%3C%40U123%3EHog/posthog/pull/123" in reply.content
        assert "<@" not in reply.content
        if expected_public:
            assert str(self.report.id) not in reply.content
            assert ticket_message_type(reply.item_context, reply.created_by_id) == TicketMessageType.SENT_REPLY
            delivery = ConversationDelivery.objects.for_team(self.team.id).get(comment_id=reply.id)
            assert delivery.route == {"channel": "C123", "thread_ts": "1700000000.000100"}
        else:
            assert ticket_message_type(reply.item_context, reply.created_by_id) == TicketMessageType.INTERNAL_NOTE
            assert not ConversationDelivery.objects.for_team(self.team.id).filter(comment_id=reply.id).exists()

    def test_linking_pull_request_queues_ticket_note_only_after_verification(self):
        pr_url = "https://github.com/PostHog/posthog/pull/123"
        task = Task.objects.create(team=self.team, created_by=self.user)
        SignalReportTask.objects.create(team=self.team, report=self.report, task=task, relationship="implementation")
        details = PullRequestDetails(
            url=pr_url, repository="PostHog/posthog", number=123, state="unknown", merged=False
        )

        with (
            patch("products.tasks.backend.facade.api.is_verified_task_pr_url") as verified,
            patch("products.signals.backend.tasks.write_pull_request_to_support_tickets.delay") as send_note,
        ):
            verified.return_value = False
            with self.captureOnCommitCallbacks(execute=True):
                link_pull_request(
                    report=self.report,
                    details=details,
                    actor=ArtefactAttribution.from_task(str(task.id)),
                    claim_id=None,
                    state_source=PullRequestStateSource.TASK_OUTPUT,
                    notify_reviewers=False,
                )
            send_note.assert_not_called()
            verified.return_value = True
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

        assert send_note.call_count == 2
        send_note.assert_called_with(self.team.pk, str(self.report.id), pr_url, str(task.id))

    def test_unrelated_task_cannot_queue_ticket_note(self):
        task = Task.objects.create(team=self.team, created_by=self.user)
        details = PullRequestDetails(
            url="https://github.com/PostHog/posthog/pull/123",
            repository="PostHog/posthog",
            number=123,
            state="unknown",
            merged=False,
        )
        with (
            patch("products.tasks.backend.facade.api.is_verified_task_pr_url", return_value=True),
            patch("products.signals.backend.tasks.write_pull_request_to_support_tickets.delay") as send_note,
            self.captureOnCommitCallbacks(execute=True),
        ):
            link_pull_request(
                report=self.report,
                details=details,
                actor=ArtefactAttribution.from_task(str(task.id)),
                claim_id=None,
                notify_reviewers=False,
            )
        send_note.assert_not_called()

    def test_worker_rechecks_verified_task_pr_before_ticket_write(self):
        from products.signals.backend.tasks import write_pull_request_to_support_tickets

        pr_url = "https://github.com/PostHog/posthog/pull/123"
        task = Task.objects.create(team=self.team, created_by=self.user)
        SignalReportTask.objects.create(team=self.team, report=self.report, task=task, relationship="implementation")
        run = TaskRun.objects.create(team=self.team, task=task, state={})

        with patch("products.signals.backend.tasks.fetch_signals_for_report_sync", return_value=[self.signal]):
            write_pull_request_to_support_tickets.run(self.team.pk, str(self.report.id), pr_url, str(task.id))
            assert not _ticket_notes(self.team, self.ticket).exists()

            run.state = {"verified_pr_urls": [pr_url]}
            run.save(update_fields=["state"])
            write_pull_request_to_support_tickets.run(self.team.pk, str(self.report.id), pr_url, str(task.id))

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
