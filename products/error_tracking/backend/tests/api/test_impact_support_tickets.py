from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.support_tickets import (
    SupportTicketsRecommendation,
    TeamTickets,
    Ticket,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


class TestSupportTicketsLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    @parameterized.expand(
        [
            ("all_tickets_listed", 5, ["CardSubmit"]),
            # Past the list's limit the team has far more tickets than listed, so the usual rate is far higher.
            ("more_tickets_than_the_list_holds", 60, []),
        ]
    )
    def test_flags_issue_followed_by_support_tickets(self, _name: str, total_tickets: int, flagged_names: list[str]):
        issue = self._create_issue("CardSubmit")
        start = timezone.now() - timedelta(days=2)
        tickets = []
        for i in range(220):
            session_id = str(uuid7())
            seen_at = start + timedelta(minutes=i)
            properties = {"$session_id": session_id}
            _create_event(
                distinct_id=session_id, event="$pageview", team=self.team, properties=properties, timestamp=seen_at
            )
            if i >= 20:
                continue
            _create_event(
                distinct_id=session_id,
                event="$exception",
                team=self.team,
                properties={**properties, "$exception_fingerprint": f"fp::{issue.id}"},
                timestamp=seen_at,
            )
            # Four tickets come a minute after the error, and one only after ten minutes, too late to count.
            if i < 5:
                delay = timedelta(minutes=10 if i == 4 else 1)
                tickets.append(
                    Ticket(id=f"ticket-{i}", number=100 + i, session_id=session_id, created_at=seen_at + delay)
                )
        flush_persons_and_events()

        # Tickets live in Postgres behind HogQL's system.support_tickets, which ClickHouse reads over the network.
        with patch(
            "products.error_tracking.backend.logic.recommendations.support_tickets._fetch_tickets",
            return_value=TeamTickets(tickets=tickets, total=total_tickets),
        ):
            meta = SupportTicketsRecommendation().compute(self.team)

        self.assertEqual((meta["tickets"], meta["tickets_with_errors"]), (total_tickets, 4))
        self.assertEqual([i["name"] for i in meta["issues"]], flagged_names)
        if flagged_names:
            flagged = meta["issues"][0]
            self.assertEqual((flagged["tickets"], flagged["sessions"]), (4, 20))
            self.assertEqual([ref["number"] for ref in flagged["ticket_refs"]], [103, 102, 101, 100])
