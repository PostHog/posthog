from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.logic.sources import list_github_sources
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    _run_row,
    create_github_source,
    create_github_warehouse_table,
)

from ee.models.rbac.access_control import AccessControl


class TestListGithubSourcesAccessControl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

    def test_none_resource_access_fails_closed_to_self_created_sources(self) -> None:
        # filter_queryset_by_access_level returns the queryset UNFILTERED for a user with "none"
        # resource access and no object grants — without the guard, such a user enumerates every
        # GitHub source on the team.
        mine = create_github_source(self.team, prefix="mine_", source_id="gh-mine")
        mine.created_by = self.user
        mine.save()
        theirs = create_github_source(self.team, prefix="theirs_", source_id="gh-theirs")
        access_control = UserAccessControl(user=self.user, team=self.team)

        assert len(list_github_sources(team=self.team, user_access_control=access_control)) == 2

        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="none")
        visible = list_github_sources(
            team=self.team, user_access_control=UserAccessControl(user=self.user, team=self.team)
        )
        assert [source.id for source in visible] == [str(mine.id)]

        # An explicit object grant survives the fail-closed guard.
        AccessControl.objects.create(
            team=self.team, resource="external_data_source", resource_id=str(theirs.id), access_level="editor"
        )
        visible = list_github_sources(
            team=self.team, user_access_control=UserAccessControl(user=self.user, team=self.team)
        )
        assert {source.id for source in visible} == {str(mine.id), str(theirs.id)}


class TestEngineeringAnalyticsViews(ClickhouseTestMixin, BaseTest):
    """The curated query builders, exercised as inline subqueries over real
    warehouse tables. Skips when object storage is unreachable so the suite still
    runs without the dev stack."""

    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
        return create_github_warehouse_table(self, base_name, columns, rows)

    def _select(self, sql: str) -> list[tuple]:
        return execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results

    def test_pull_requests_view_maps_columns(self) -> None:
        table_name = self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    10,
                    "alice",
                    "closed",
                    0,
                    "2026-01-10 10:00:00",
                    merged_at="2026-01-12 10:00:00",
                    head_sha="sha10",
                    labels=("bug", "p1"),
                ),
                _pr_row(11, "dependabot[bot]", "closed", 0, "2026-01-11 10:00:00", merged_at="2026-01-11 12:00:00"),
                _pr_row(12, "charlie", "open", 1, "2026-01-08 10:00:00"),
            ],
        )

        rows = self._select(
            "SELECT number, author_handle, is_bot, repo_owner, repo_name, labels, state, is_draft, "
            "head_sha, open_to_merge_seconds "
            f"FROM ({pull_requests.build_query(table_name)}) AS pr ORDER BY number"
        )

        by_number = {row[0]: row for row in rows}
        # merged human PR with labels and a head sha
        assert by_number[10][1:] == (
            "alice",
            False,
            "PostHog",
            "posthog",
            ["bug", "p1"],
            "merged",
            False,
            "sha10",
            172800,
        )
        # bot detection from the [bot] suffix (ClickHouse Bool comes back as 1/0)
        assert by_number[11][2] == 1
        # open PR: state passthrough, draft flag, null duration
        assert by_number[12][6] == "open"
        assert by_number[12][7] == 1
        assert by_number[12][9] is None

    def test_workflow_runs_view_maps_columns(self) -> None:
        table_name = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(2001, "CI", "sha1", "completed", "success", "2026-01-20 10:00:00", "2026-01-20 10:30:00"),
                _run_row(2002, "CI", "sha2", "completed", "failure", "2026-01-22 10:00:00", "2026-01-22 10:45:00"),
                _run_row(2003, "Deploy", "sha3", "in_progress", None, "2026-01-25 10:00:00", "2026-01-25 10:05:00"),
            ],
        )

        rows = self._select(
            "SELECT workflow_name, status, conclusion, duration_seconds, repo_owner, repo_name "
            f"FROM ({workflow_runs.build_query(table_name)}) AS r ORDER BY id"
        )

        # completed runs carry a duration; in-progress run has null duration and null conclusion
        assert rows[0] == ("CI", "completed", "success", 1800, "PostHog", "posthog")
        assert rows[1][3] == 2700
        assert rows[2] == ("Deploy", "in_progress", None, None, "PostHog", "posthog")

    def test_pull_requests_view_handles_null_user(self) -> None:
        # The real source lands user as Nullable(String), NULL for a PR by a deleted GitHub account.
        # JSONExtractString over a NULL Nullable returns NULL, so the builder must ifNull-guard it to
        # '' — else author_handle/avatar_url come back NULL and the non-null Author contract 500s.
        # Driven through an inline constant source (nullIf('', '') is a typed NULL) so it runs whether
        # or not object storage is available.
        head_json = '{"sha": "sha5"}'
        base_json = '{"repo": {"full_name": "PostHog/posthog"}}'
        raw = (
            "(SELECT 100 AS id, 5 AS number, 'PR 5' AS title, 'open' AS state, false AS draft, "
            f"nullIf('', '') AS user, '{head_json}' AS head, '{base_json}' AS base, '[]' AS labels, "
            "'2026-01-10 10:00:00' AS created_at, '2026-01-10 10:00:00' AS updated_at, "
            "nullIf('', '') AS merged_at, nullIf('', '') AS closed_at)"
        )
        rows = self._select(
            f"SELECT author_handle, author_avatar_url, is_bot FROM ({pull_requests.build_query(raw)}) AS pr"
        )
        assert rows[0] == ("", "", 0)

    def test_workflow_runs_view_handles_null_pull_requests(self) -> None:
        # The real source lands pull_requests as Nullable(String), so it can be NULL (a run with no
        # PR association). The builder's ifNull(pull_requests, '[]') guard must carry that NULL to
        # pr_number = 0 (unattributed), never letting JSONExtractArrayRaw see a Nullable. Driven
        # through an inline constant source (nullIf('', '') is a typed NULL) so it exercises the
        # guard whether or not object storage is available — unlike the table-backed tests, which
        # skip without it.
        repo_json = '{"full_name": "PostHog/posthog"}'
        raw = (
            "(SELECT 1 AS id, 'CI' AS name, 'sha1' AS head_sha, 'main' AS head_branch, 'completed' AS status, "
            "'success' AS conclusion, 1 AS run_attempt, nullIf('', '') AS pull_requests, "
            f"'{repo_json}' AS repository, "
            "'2026-01-20 10:00:00' AS run_started_at, '2026-01-20 10:30:00' AS updated_at, "
            "'2026-01-20 10:00:00' AS created_at)"
        )
        rows = self._select(f"SELECT pr_number, repo_owner, repo_name FROM ({workflow_runs.build_query(raw)}) AS r")
        assert rows[0] == (0, "PostHog", "posthog")

    def test_workflow_runs_view_tolerates_all_nullable_columns(self) -> None:
        # Prod lands every column Nullable, so a single run can carry NULL across timestamps,
        # repository, pull_requests and run_attempt at once (e.g. a barely-started run). Driven
        # through a real warehouse table built from the shared (now fully-Nullable) schema — the
        # exact prod shape — to prove the builder maps it instead of 500ing: NULL timestamps ->
        # NULL duration, NULL repository -> empty owner/name, NULL pull_requests -> pr_number 0.
        sparse_run: dict[str, Any] = {
            "id": 4001,
            "name": "CI",
            "head_sha": "shaQ",
            "status": "completed",
            "conclusion": None,
            "created_at": None,
            "run_started_at": None,
            "updated_at": None,
            "run_attempt": None,
            "pull_requests": None,
            "repository": None,
        }
        table_name = self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [sparse_run])
        rows = self._select(
            "SELECT status, conclusion, duration_seconds, repo_owner, repo_name, pr_number, run_attempt "
            f"FROM ({workflow_runs.build_query(table_name)}) AS r"
        )
        assert rows[0] == ("completed", None, None, "", "", 0, None)
