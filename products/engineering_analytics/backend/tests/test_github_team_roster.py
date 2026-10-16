from posthog.test.base import BaseTest, ClickhouseTestMixin

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import GitHubTeamMembership, GitHubTeamRoster
from products.engineering_analytics.backend.logic.views.source_schema import TEAM_MEMBERS_COLUMNS
from products.engineering_analytics.backend.tests._logic_helpers import _WarehouseMixin

_WITHOUT_ROLE = {name: spec for name, spec in TEAM_MEMBERS_COLUMNS.items() if name != "role"}


def _member_row(member_id: int, login: str, team_slug: str, role: str) -> dict:
    return {
        "id": member_id,
        "login": login,
        "role": role,
        "team_id": 1,
        "team_slug": team_slug,
        "team_name": team_slug.removeprefix("team-").title(),
    }


class TestGitHubTeamRoster(_WarehouseMixin, ClickhouseTestMixin, BaseTest):
    """The roster read end to end over a real warehouse table, with no PR/CI endpoints seeded."""

    def test_reads_the_roster_from_a_source_that_syncs_membership_alone(self) -> None:
        # Guards the HogQL and the narrow resolver together: the read runs without pull_requests /
        # workflow_runs, lowercases the login, and carries the role. A break here is invisible,
        # because the caller degrades to "not synced" rather than raising.
        self._create_table(
            "github_team_members",
            TEAM_MEMBERS_COLUMNS,
            [
                _member_row(1, "Boss", "team-desktop", "maintainer"),
                _member_row(2, "plain", "team-desktop", "member"),
                # A per-repo sync of an org-scoped endpoint lands this membership twice: it must
                # collapse to one row without demoting the maintainer.
                _member_row(5, "boss", "team-desktop", "member"),
                # Rows GitHub can land that reach no reader: no login to match, no team to file under.
                _member_row(3, "", "team-desktop", "member"),
                _member_row(4, "nobody", "", "member"),
            ],
        )

        roster = api.get_github_team_roster(team=self.team)

        assert roster == GitHubTeamRoster(
            memberships=(
                GitHubTeamMembership(
                    member_handle="boss", team_slug="team-desktop", team_name="Desktop", is_maintainer=True
                ),
                GitHubTeamMembership(
                    member_handle="plain", team_slug="team-desktop", team_name="Desktop", is_maintainer=False
                ),
            ),
            synced=True,
        )

    def test_a_snapshot_without_roles_reports_every_member_as_a_plain_member(self) -> None:
        # GitHub omits role from the documented member object, so a table can land without the column.
        self._create_table("github_team_members", _WITHOUT_ROLE, [_member_row(1, "boss", "team-desktop", "maintainer")])

        roster = api.get_github_team_roster(team=self.team)

        assert [membership.is_maintainer for membership in roster.memberships] == [False]

    def test_reports_not_synced_without_a_membership_snapshot(self) -> None:
        assert api.get_github_team_roster(team=self.team) == GitHubTeamRoster(memberships=(), synced=False)
