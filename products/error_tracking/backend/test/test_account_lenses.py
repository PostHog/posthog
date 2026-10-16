from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.account_reach import (
    AccountReach,
    IssueAccounts,
    TeamAccounts,
)
from products.error_tracking.backend.logic.recommendations.many_accounts import find_many_accounts
from products.error_tracking.backend.logic.recommendations.one_account import find_one_account

TEAM_ID = 1


def reach(*, sessions: int, accounts: int, top_account: str, top_sessions: int, active_accounts: int) -> AccountReach:
    return AccountReach(
        issues=[
            IssueAccounts(
                team_id=TEAM_ID,
                issue_id="issue",
                people=sessions,
                sessions=sessions,
                accounts=accounts,
                top_account=top_account,
                top_account_sessions=top_sessions,
            )
        ],
        teams={TEAM_ID: TeamAccounts(active_accounts=active_accounts)},
    )


class TestAccountLenses(SimpleTestCase):
    @parameterized.expand(
        [
            # name, accounts, active accounts, flagged
            ("reaches_many_accounts", 40, 200, True),
            ("too_few_accounts", 9, 100, False),
            ("small_share_of_active_accounts", 12, 1000, False),
            ("no_active_accounts", 40, 0, False),
        ]
    )
    def test_many_accounts(self, _name: str, accounts: int, active_accounts: int, flagged: bool) -> None:
        found = find_many_accounts(
            reach(sessions=80, accounts=accounts, top_account="acct-1", top_sessions=2, active_accounts=active_accounts)
        )

        self.assertEqual(bool(found.get(TEAM_ID)), flagged)

    @parameterized.expand(
        [
            # name, sessions, top account, top account sessions, flagged
            ("one_account_causes_most_sessions", 32, "acct-1", 29, True),
            ("too_few_sessions", 12, "acct-1", 11, False),
            ("largest_account_below_half", 40, "acct-1", 15, False),
            ("no_account_on_events", 40, "", 0, False),
        ]
    )
    def test_one_account(self, _name: str, sessions: int, top_account: str, top_sessions: int, flagged: bool) -> None:
        found = find_one_account(
            reach(
                sessions=sessions, accounts=4, top_account=top_account, top_sessions=top_sessions, active_accounts=200
            )
        )

        self.assertEqual(bool(found.get(TEAM_ID)), flagged)
