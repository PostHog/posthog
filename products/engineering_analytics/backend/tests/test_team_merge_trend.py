from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.team_merge_trend import query_team_merge_trend
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import PULL_REQUESTS_COLUMNS, TEAM_MEMBERS_COLUMNS
from products.engineering_analytics.backend.tests.test_views import (
    _pr_row,
    connect_github_source_without_data,
    create_github_warehouse_table,
)


def _member_row(member_id: int, login: str, team_slug: str) -> dict:
    return {
        "id": member_id,
        "login": login,
        "team_id": 1,
        "team_slug": team_slug,
        "team_name": team_slug,
    }


class TestTeamMergeTrendAPI(ClickhouseTestMixin, APIBaseTest):
    def test_degrades_without_membership_snapshot_and_requires_owner_team(self):
        # The source resolves (pull_requests + workflow_runs) but has no team_members schema:
        # the endpoint must answer has_membership_data=false instead of querying a missing table.
        connect_github_source_without_data(self.team, prefix="mt", repository="PostHog/posthog")

        response = self.client.get(
            f"/api/projects/{self.team.id}/engineering_analytics/team_merge_trend/",
            {"owner_team": "team-replay"},
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"owner_team": "team-replay", "has_membership_data": False, "points": []}

        missing = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/team_merge_trend/")
        assert missing.status_code == status.HTTP_400_BAD_REQUEST


class TestTeamMergeTrendQuery(ClickhouseTestMixin, BaseTest):
    def _curated(self, team: Team, pr_rows: list[dict], member_rows: list[dict]) -> CuratedGitHubSource:
        pr_table = create_github_warehouse_table(self, "github_pull_requests", PULL_REQUESTS_COLUMNS, pr_rows)
        members_table = create_github_warehouse_table(self, "github_team_members", TEAM_MEMBERS_COLUMNS, member_rows)
        return CuratedGitHubSource(
            team=team,
            tables=GitHubTables(pull_requests=pr_table, workflow_runs="unused", team_members=members_table),
        )

    def test_membership_join_bot_exclusion_and_window(self):
        # Guards the freshly written HogQL: the daily median/average must cover exactly the
        # slug's members' merges, bots and non-members must stay out, and the window must
        # bound merged_at.
        curated = self._curated(
            self.team,
            pr_rows=[
                # 2026-01-12, alice (team-replay): 2h + 4h + 30h merges, a skew that separates
                # the median (4h) from the average (12h).
                _pr_row(1, "alice", "closed", 0, "2026-01-12 08:00:00", merged_at="2026-01-12 10:00:00"),
                _pr_row(2, "alice", "closed", 0, "2026-01-12 08:00:00", merged_at="2026-01-12 12:00:00"),
                _pr_row(3, "alice", "closed", 0, "2026-01-11 08:00:00", merged_at="2026-01-12 14:00:00"),
                # Same day: a non-member and a bot merge too; neither may move the team's numbers.
                _pr_row(4, "bob", "closed", 0, "2026-01-11 10:00:00", merged_at="2026-01-12 10:00:00"),
                _pr_row(5, "dependabot[bot]", "closed", 0, "2026-01-12 09:00:00", merged_at="2026-01-12 10:00:00"),
                # 2026-01-14: only the non-member merges, so no team row for the day.
                _pr_row(6, "bob", "closed", 0, "2026-01-14 00:00:00", merged_at="2026-01-14 10:00:00"),
                # Outside the window / never merged: excluded entirely.
                _pr_row(7, "alice", "closed", 0, "2026-01-30 10:00:00", merged_at="2026-02-01 10:00:00"),
                _pr_row(8, "alice", "open", 0, "2026-01-11 10:00:00"),
            ],
            member_rows=[
                _member_row(1, "alice", "team-replay"),
                _member_row(2, "bob", "team-ingestion"),
            ],
        )

        result = query_team_merge_trend(
            curated=curated,
            owner_team="team-replay",
            date_from=datetime(2026, 1, 10, tzinfo=UTC),
            date_to=datetime(2026, 1, 20, tzinfo=UTC),
        )

        assert result.has_membership_data is True
        assert [point.day.date().isoformat() for point in result.points] == ["2026-01-12"]
        (point,) = result.points
        assert (point.median_seconds, point.average_seconds, point.merged_count) == (14400.0, 43200.0, 3)
