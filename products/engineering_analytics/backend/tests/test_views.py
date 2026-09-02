import json
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.engineering_analytics.backend.logic.sources import (
    TRUNK_MERGE_QUEUE_SCHEMA,
    list_github_sources,
    resolve_trunk_merge_queue_table,
)
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
    create_trunk_source,
    create_warehouse_table_row,
    link_schema,
    pr_association,
    pr_association_entry,
    repo_id,
)


class TestListGithubSourcesAccessControl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

    def test_none_resource_access_fails_closed_to_self_created_sources(self) -> None:
        # A user with "none" resource access and no object grants must not enumerate the
        # team's sources. The product surface relies on filter_queryset_by_access_level to
        # fail closed here.
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

        # An explicit object grant survives the fail-closed guard. The filter counts only member
        # and role rows as grants. A default ("everyone") object row does not count.
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=str(theirs.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )
        visible = list_github_sources(
            team=self.team, user_access_control=UserAccessControl(user=self.user, team=self.team)
        )
        assert {source.id for source in visible} == {str(mine.id), str(theirs.id)}

    def test_trunk_resolver_denied_user_resolves_none(self) -> None:
        # The trunk resolver feeds team-scoped HogQL that enforces no per-user ACL, so it must apply
        # the same source RBAC as the GitHub path: a user denied every TrunkIo source resolves None
        # (consumers degrade to the failed-gate proxy) instead of reading the queue table.
        source = create_trunk_source(self.team)
        table = create_warehouse_table_row(
            self.team, name="trunkprefix_trunk_io_merge_queue_pull_requests", source=source
        )
        link_schema(self.team, source, name=TRUNK_MERGE_QUEUE_SCHEMA, table=table)

        assert resolve_trunk_merge_queue_table(self.team) == table.name
        assert (
            resolve_trunk_merge_queue_table(self.team, UserAccessControl(user=self.user, team=self.team)) == table.name
        )

        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="none")
        assert resolve_trunk_merge_queue_table(self.team, UserAccessControl(user=self.user, team=self.team)) is None


class TestEngineeringAnalyticsViews(ClickhouseTestMixin, BaseTest):
    """The curated query builders, exercised as inline subqueries over real
    warehouse tables."""

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
                _pr_row(
                    13,
                    "trunk-io[bot]",
                    "open",
                    1,
                    "2026-01-13 10:00:00",
                    head_ref="trunk-merge/pr-10/cabec75e-5181-4429-aea5-0501a52d0688",
                ),
                # Same branch shape, ordinary author: branch names are contributor-controlled, so
                # dropping on the shape alone would let anyone delete their own PR from every surface
                # here (or someone else's runs onto a PR of their choosing).
                _pr_row(
                    14,
                    "mallory",
                    "open",
                    0,
                    "2026-01-14 10:00:00",
                    head_ref="trunk-merge/pr-10/deadbeef-0000-0000-0000-000000000000",
                ),
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
        # A merge-queue gate branch is a CI artifact, not a PR — dropped here so no PR surface
        # (list, cards, medians) has to remember to exclude it. Only when the queue bot authored it:
        # PR 14 wears the same branch shape but a human's name, and must survive.
        assert 13 not in by_number
        assert 14 in by_number

    def test_workflow_runs_view_maps_columns(self) -> None:
        table_name = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(2001, "CI", "sha1", "completed", "success", "2026-01-20 10:00:00", "2026-01-20 10:30:00"),
                _run_row(2002, "CI", "sha2", "completed", "failure", "2026-01-22 10:00:00", "2026-01-22 10:45:00"),
                _run_row(2003, "Deploy", "sha3", "in_progress", None, "2026-01-25 10:00:00", "2026-01-25 10:05:00"),
                _run_row(
                    2004,
                    "CI",
                    "sha4",
                    "completed",
                    "success",
                    "2026-01-26 10:00:00",
                    "2026-01-26 10:20:00",
                    # A gate run's own association names the throwaway PR the queue opened (9001);
                    # the branch names the PR being landed (44), which is the one every surface asks
                    # about. Reading the association here loses the gate run from that PR's rollup
                    # and cost, and files it under a PR no surface shows.
                    pr_number=9001,
                    head_branch="trunk-merge/pr-44/cabec75e-5181-4429-aea5-0501a52d0688",
                    actor="trunk-io[bot]",
                ),
                # Same branch shape, ordinary actor. Branch names are contributor-controlled, so on
                # the shape alone this would re-key a stranger's runs and CI cost onto PR 44.
                _run_row(
                    2005,
                    "CI",
                    "sha5",
                    "completed",
                    "success",
                    "2026-01-27 10:00:00",
                    "2026-01-27 10:20:00",
                    pr_number=9002,
                    head_branch="trunk-merge/pr-44/deadbeef-0000-0000-0000-000000000000",
                    actor="mallory",
                ),
            ],
        )

        rows = self._select(
            "SELECT workflow_name, status, conclusion, duration_seconds, repo_owner, repo_name, "
            "pr_number, is_merge_queue "
            f"FROM ({workflow_runs.build_query(table_name)}) AS r ORDER BY id"
        )

        # completed runs carry a duration; in-progress run has null duration and null conclusion
        assert rows[0][:6] == ("CI", "completed", "success", 1800, "PostHog", "posthog")
        assert rows[1][3] == 2700
        assert rows[2][:6] == ("Deploy", "in_progress", None, None, "PostHog", "posthog")
        assert rows[3][6:] == (44, 1)
        # Spoofed shape without the queue actor: attribution stays on the run's own association.
        assert rows[4][6:] == (9002, 0)

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
            "nullIf('', '') AS merged_at, nullIf('', '') AS closed_at, nullIf('', '') AS merge_commit_sha)"
        )
        rows = self._select(
            f"SELECT author_handle, author_avatar_url, is_bot FROM ({pull_requests.build_query(raw)}) AS pr"
        )
        assert rows[0] == ("", "", 0)

    def test_workflow_runs_view_handles_null_pull_requests(self) -> None:
        # The real source lands pull_requests as Nullable(String), so it can be NULL (a run with no
        # PR association). The builder's ifNull(pull_requests, '[]') guard must carry that NULL to
        # pr_number = 0 (unattributed), never letting JSONExtractArrayRaw see a Nullable. ``actor``
        # is Nullable the same way, and it gates the merge-queue branch parse — a NULL there must
        # read as "not the queue", not poison the whole expression to NULL. Driven through an inline
        # constant source (nullIf('', '') is a typed NULL) so it exercises the guards whether or not
        # object storage is available — unlike the table-backed tests, which skip without it.
        repo_json = '{"full_name": "PostHog/posthog"}'
        raw = (
            "(SELECT 1 AS id, 'CI' AS name, 'sha1' AS head_sha, "
            "'trunk-merge/pr-44/cabec75e' AS head_branch, 'completed' AS status, "
            "'success' AS conclusion, 1 AS run_attempt, nullIf('', '') AS pull_requests, "
            f"'{repo_json}' AS repository, nullIf('', '') AS head_commit, nullIf('', '') AS actor, "
            "'2026-01-20 10:00:00' AS run_started_at, '2026-01-20 10:30:00' AS updated_at, "
            "'2026-01-20 10:00:00' AS created_at)"
        )
        rows = self._select(
            f"SELECT pr_number, repo_owner, repo_name, is_merge_queue FROM ({workflow_runs.build_query(raw)}) AS r"
        )
        assert rows[0] == (0, "PostHog", "posthog", 0)

    def test_workflow_runs_view_attributes_only_own_repo_prs_and_falls_back_to_the_merge_commit(self) -> None:
        # GitHub's pull_requests association lists every PR in the fork network sharing the run's
        # head SHA, so a push to our default branch arrives carrying downstream forks' "sync from
        # upstream" PRs. Taking the first entry unfiltered credited those runs to a stranger's PR
        # number under our own owner/name. Only a base.repo.id matching the run's repository.id is
        # ours; a push's real attribution is the (#NNNN) squash-merge suffix instead.
        own, fork = "PostHog/posthog", "Mu-L/posthog-1"
        cases: list[tuple[str, str | None, str | None, int, int | None]] = [
            # (head_branch, pull_requests, commit message, expected pr_number, expected commit_pr_number)
            ("pr-branch", pr_association(42, base_repo=own), "feat: wip", 42, None),
            # The real master-push shape: only foreign entries, so nothing is ours.
            ("master", pr_association(1379, 3, base_repo=fork), "feat: thing (#73832)", 0, 73832),
            # A foreign entry listed FIRST must not shadow ours — position is what the old code used.
            (
                "pr-branch",
                json.dumps([pr_association_entry(1379, base_repo=fork), pr_association_entry(42, base_repo=own)]),
                "feat: wip",
                42,
                None,
            ),
            ("master", None, "chore: direct push", 0, None),
        ]
        rows = [
            {
                "id": 5000 + index,
                "name": "CI",
                "head_sha": f"sha{index}",
                "head_branch": head_branch,
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-01-20 10:00:00",
                "run_started_at": "2026-01-20 10:00:00",
                "updated_at": "2026-01-20 10:30:00",
                "run_attempt": 1,
                "pull_requests": association,
                "repository": json.dumps({"full_name": own, "id": repo_id(own)}),
                "head_commit": json.dumps({"message": message}),
            }
            for index, (head_branch, association, message, _, _) in enumerate(cases)
        ]
        table_name = self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, rows)

        results = self._select(
            f"SELECT id, pr_number, commit_pr_number FROM ({workflow_runs.build_query(table_name)}) AS r ORDER BY id"
        )
        assert results == [(5000 + index, pr, commit_pr) for index, (_, _, _, pr, commit_pr) in enumerate(cases)]

    def test_workflow_runs_view_resolves_default_branch_pushes_through_the_merge_commit(self) -> None:
        # A default-branch push carries no association of its own, so commit_pr_number is the only
        # attribution it gets. The merged PR's merge_commit_sha IS that run's head SHA, which
        # resolves landings the (#NNNN) message suffix can't, but it must be read only off a
        # MERGED PR, since GitHub fills it on an open one with a throwaway test-merge commit.
        own = "PostHog/posthog"
        cases: list[tuple[str, str, int | None]] = [
            # (head_sha, commit message, expected commit_pr_number)
            # The case only the join serves: a merge-commit landing, no (#NNNN) in the subject.
            ("shaA", "fix: regenerate generated types", 101),
            # An open PR's merge_commit_sha is a test merge, not a landing, so it must not attribute.
            ("shaB", "chore: direct push", None),
            # Join miss (no PR row for this SHA) still falls back to the message suffix.
            ("shaC", "feat: thing (#103)", 103),
            # Several merged PRs sharing one merge commit stay ONE run row, not one per PR.
            ("shaD", "feat: stacked landing (#104)", 104),
        ]
        prs = [
            _pr_row(
                101,
                "alice",
                "closed",
                0,
                "2026-01-19 09:00:00",
                merged_at="2026-01-20 09:00:00",
                merge_commit_sha="shaA",
            ),
            _pr_row(102, "bob", "open", 0, "2026-01-19 09:00:00", merge_commit_sha="shaB"),
            _pr_row(
                104,
                "carol",
                "closed",
                0,
                "2026-01-19 09:00:00",
                merged_at="2026-01-20 09:00:00",
                merge_commit_sha="shaD",
            ),
            _pr_row(
                105,
                "dave",
                "closed",
                0,
                "2026-01-19 09:00:00",
                merged_at="2026-01-20 09:00:00",
                merge_commit_sha="shaD",
            ),
        ]
        runs = [
            {
                "id": 6000 + index,
                "name": "CI",
                "head_sha": head_sha,
                "head_branch": "master",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-01-20 10:00:00",
                "run_started_at": "2026-01-20 10:00:00",
                "updated_at": "2026-01-20 10:30:00",
                "run_attempt": 1,
                "pull_requests": None,
                "repository": json.dumps({"full_name": own, "id": repo_id(own)}),
                "head_commit": json.dumps({"message": message}),
            }
            for index, (head_sha, message, _) in enumerate(cases)
        ]
        prs_table = self._create_table("github_pull_requests", PULL_REQUESTS_COLUMNS, prs)
        runs_table = self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, runs)

        query = workflow_runs.build_query(runs_table, pull_requests_table=prs_table)
        results = self._select(f"SELECT id, commit_pr_number FROM ({query}) AS r ORDER BY id")
        assert results == [(6000 + index, expected) for index, (_, _, expected) in enumerate(cases)]

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
