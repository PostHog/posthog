import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

import pandas as pd

from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
)
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS as _PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS as _WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.views"

# Non-default prefix on purpose: every fixture below lands tables named
# `myprefixgithub_*`, so the resolver and builders are proven against a name the old
# hardcoded `github_*` constants would never have matched.
GITHUB_SOURCE_PREFIX = "myprefix"


def create_github_source(
    team: Team, *, prefix: str = GITHUB_SOURCE_PREFIX, source_id: str = "gh-source"
) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=source_id,
        connection_id=source_id,
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.GITHUB,
        prefix=prefix,
    )


def link_schema(
    team: Team,
    source: ExternalDataSource,
    *,
    name: str,
    table: DataWarehouseTable | None,
    should_sync: bool = True,
) -> ExternalDataSchema:
    return ExternalDataSchema.objects.create(team=team, source=source, name=name, table=table, should_sync=should_sync)


def create_warehouse_table_row(
    team: Team, *, name: str, source: ExternalDataSource | None = None
) -> DataWarehouseTable:
    # ORM-only table (no object storage); for resolver/mapping tests that mock the query.
    return DataWarehouseTable.objects.create(
        team=team,
        name=name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        url_pattern="",
        external_data_source=source,
        columns={},
    )


def connect_github_source_without_data(team: Team, *, prefix: str = GITHUB_SOURCE_PREFIX) -> GitHubTables:
    """A GitHub source with pull_requests/workflow_runs schemas over empty ORM tables.

    The resolver finds these without touching object storage; pair with a mocked query
    when only resolution (not real warehouse data) matters.
    """
    source = create_github_source(team, prefix=prefix)
    pr_table = create_warehouse_table_row(team, name=f"{prefix}github_pull_requests", source=source)
    run_table = create_warehouse_table_row(team, name=f"{prefix}github_workflow_runs", source=source)
    link_schema(team, source, name=PULL_REQUESTS_SCHEMA, table=pr_table)
    link_schema(team, source, name=WORKFLOW_RUNS_SCHEMA, table=run_table)
    return GitHubTables(pull_requests=pr_table.name, workflow_runs=run_table.name)


def _user(login: str) -> str:
    return f'{{"login": "{login}", "avatar_url": "https://avatars/{login}"}}'


def _base(full_name: str, ref: str = "") -> str:
    return f'{{"ref": "{ref}", "repo": {{"full_name": "{full_name}"}}}}'


def _labels(*names: str) -> str:
    return "[" + ", ".join(f'{{"name": "{name}"}}' for name in names) + "]"


def _pr_row(
    number: int,
    login: str,
    state: str,
    draft: int,
    created_at: str,
    *,
    merged_at: str | None = None,
    head_sha: str = "",
    head_ref: str = "",
    base_ref: str = "",
    full_name: str = "PostHog/posthog",
    labels: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": 1000 + number,
        "number": number,
        "title": f"PR {number}",
        "state": state,
        "draft": draft,
        "created_at": created_at,
        "updated_at": merged_at or created_at,
        "merged_at": merged_at,
        "closed_at": merged_at,
        "user": _user(login),
        "head": f'{{"sha": "{head_sha}", "ref": "{head_ref}"}}',
        "base": _base(full_name, base_ref),
        "labels": _labels(*labels),
    }


def _run_row(
    run_id: int,
    name: str,
    head_sha: str,
    status: str,
    conclusion: str | None,
    run_started_at: str,
    updated_at: str,
    *,
    full_name: str = "PostHog/posthog",
    run_attempt: int = 1,
    pr_number: int | None = None,
    head_branch: str = "main",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "status": status,
        "conclusion": conclusion,
        "created_at": run_started_at,
        "run_started_at": run_started_at,
        "updated_at": updated_at,
        "run_attempt": run_attempt,
        # Mirror the real Nullable(String) column: an unassociated run lands NULL, not "[]",
        # so the builder's ifNull(pull_requests, '[]') guard is exercised on the real path.
        "pull_requests": f'[{{"number": {pr_number}}}]' if pr_number is not None else None,
        "repository": f'{{"full_name": "{full_name}"}}',
    }


class TestEngineeringAnalyticsViews(ClickhouseTestMixin, BaseTest):
    """The curated query builders, exercised as inline subqueries over real
    warehouse tables. Skips when object storage is unreachable so the suite still
    runs without the dev stack."""

    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
        # Returns the real table name (prefixed), which the builder is then told to read —
        # proving build_query honors the resolved name instead of a hardcoded one.
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        try:
            table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=base_name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        return table.name

    def _select(self, sql: str) -> list[tuple]:
        return execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results

    def test_pull_requests_view_maps_columns(self) -> None:
        table_name = self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
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
            _WORKFLOW_RUNS_COLUMNS,
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
        table_name = self._create_table("github_workflow_runs", _WORKFLOW_RUNS_COLUMNS, [sparse_run])
        rows = self._select(
            "SELECT status, conclusion, duration_seconds, repo_owner, repo_name, pr_number, run_attempt "
            f"FROM ({workflow_runs.build_query(table_name)}) AS r"
        )
        assert rows[0] == ("completed", None, None, "", "", 0, None)
