from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.support_tickets import find_ticket_issues


class TestFindTicketIssues(SimpleTestCase):
    @parameterized.expand(
        [
            # name, tickets, issue sessions, baseline tickets per 1,000 sessions
            ("far_above_baseline", 6, 25, 2.29, True),
            ("single_ticket", 1, 5, 2.29, False),
            ("below_three_times_baseline", 2, 1000, 1.0, False),
            ("issue_without_sessions", 3, 0, 1.0, False),
        ]
    )
    def test_flags_issues_followed_by_far_more_tickets_than_usual(
        self, _name: str, tickets: int, sessions: int, baseline: float, flagged: bool
    ) -> None:
        ticket_ids = [f"ticket-{i}" for i in range(tickets)]

        issues = find_ticket_issues({"issue": ticket_ids}, {"issue": sessions}, {}, baseline)

        self.assertEqual([issue["id"] for issue in issues], ["issue"] if flagged else [])

    def test_orders_issues_by_ticket_rate_and_keeps_ticket_numbers(self) -> None:
        linked = {"common": ["t1", "t2", "t3"], "rare": ["t4", "t5"]}
        numbers = {"t1": 11, "t2": 12, "t3": 13, "t4": 14, "t5": 15}

        issues = find_ticket_issues(linked, {"common": 300, "rare": 10}, numbers, 1.0)

        self.assertEqual([issue["id"] for issue in issues], ["rare", "common"])
        self.assertEqual([ref["number"] for ref in issues[0]["ticket_refs"]], [15, 14])
