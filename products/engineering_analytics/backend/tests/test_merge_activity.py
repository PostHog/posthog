from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.merge_activity import query_merge_activity
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import PULL_REQUESTS_COLUMNS
from products.engineering_analytics.backend.tests.test_views import _pr_row, create_github_warehouse_table


class TestMergeActivityQuery(ClickhouseTestMixin, BaseTest):
    def _curated(self, team: Team, pr_rows: list[dict]) -> CuratedGitHubSource:
        pr_table = create_github_warehouse_table(self, "github_pull_requests", PULL_REQUESTS_COLUMNS, pr_rows)
        return CuratedGitHubSource(team=team, tables=GitHubTables(pull_requests=pr_table, workflow_runs="unused"))

    def test_bot_exclusion_window_bounds_leading_floor_and_zero_fill(self):
        # Guards the freshly written HogQL plus the zero-fill spine: bot merges and out-of-window
        # merges must stay out, unmerged PRs must not count, a day with no merges must appear as a
        # real 0 (a bucket-keying type mismatch would silently zero the whole series), and a mid-day
        # date_from must floor to its bucket so the first bucket is a complete day, not a partial
        # undercount.
        curated = self._curated(
            self.team,
            pr_rows=[
                # Merged before the raw 09:30 date_from but within its floored day bucket: must count.
                _pr_row(1, "alice", "closed", 0, "2026-01-10 00:30:00", merged_at="2026-01-10 01:00:00"),
                _pr_row(2, "alice", "closed", 0, "2026-01-10 09:00:00", merged_at="2026-01-10 12:00:00"),
                _pr_row(3, "bob", "closed", 0, "2026-01-11 08:00:00", merged_at="2026-01-12 09:00:00"),
                # A bot merge on an otherwise-counted day: must not move the count.
                _pr_row(4, "dependabot[bot]", "closed", 0, "2026-01-12 08:00:00", merged_at="2026-01-12 10:00:00"),
                # Never merged / merged outside the window: excluded entirely.
                _pr_row(5, "alice", "open", 0, "2026-01-10 08:00:00"),
                _pr_row(6, "alice", "closed", 0, "2026-01-30 08:00:00", merged_at="2026-02-01 10:00:00"),
                _pr_row(7, "alice", "closed", 0, "2026-01-09 08:00:00", merged_at="2026-01-09 23:00:00"),
            ],
        )

        result = query_merge_activity(
            curated=curated,
            date_from=datetime(2026, 1, 10, 9, 30, tzinfo=UTC),
            date_to=datetime(2026, 1, 13, 12, tzinfo=UTC),
        )

        assert result.granularity == "day"
        assert [(bucket.bucket_start, bucket.merged_count) for bucket in result.buckets] == [
            (datetime(2026, 1, 10), 2),
            (datetime(2026, 1, 11), 0),
            (datetime(2026, 1, 12), 1),
            (datetime(2026, 1, 13), 0),
        ]
