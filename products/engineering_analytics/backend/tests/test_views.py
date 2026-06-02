import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

import pandas as pd

from posthog.hogql.query import execute_hogql_query

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.engineering_analytics.backend.logic.views.orchestrator import build_all_engineering_analytics_views

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.views"

_PULL_REQUESTS_COLUMNS = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "number": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "title": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "draft": {"clickhouse": "Bool", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "updated_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "merged_at": {"clickhouse": "Nullable(DateTime64(3, 'UTC'))", "hogql": "DateTimeDatabaseField"},
    "closed_at": {"clickhouse": "Nullable(DateTime64(3, 'UTC'))", "hogql": "DateTimeDatabaseField"},
    "user": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "base": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "String", "hogql": "StringDatabaseField"},
}

_WORKFLOW_RUNS_COLUMNS = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "run_started_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "updated_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "repository": {"clickhouse": "String", "hogql": "StringDatabaseField"},
}


def _user(login: str) -> str:
    return f'{{"login": "{login}", "avatar_url": "https://avatars/{login}"}}'


def _base(full_name: str) -> str:
    return f'{{"repo": {{"full_name": "{full_name}"}}}}'


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
        "head": f'{{"sha": "{head_sha}"}}',
        "base": _base(full_name),
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
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "status": status,
        "conclusion": conclusion,
        "created_at": run_started_at,
        "run_started_at": run_started_at,
        "updated_at": updated_at,
        "repository": f'{{"full_name": "{full_name}"}}',
    }


class TestEngineeringAnalyticsViews(ClickhouseTestMixin, BaseTest):
    """The curated read layer, queried by name over real warehouse tables.

    Skips when object storage is unreachable so the suite still runs without the
    dev stack."""

    def _create_table(self, name: str, columns: dict, rows: list[dict[str, Any]]) -> None:
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(lambda path=tmp.name: Path(path).unlink(missing_ok=True))
        try:
            _table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source_prefix="",
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)

    def _select(self, sql: str) -> list[tuple]:
        return execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results

    def test_gate_skips_views_when_source_absent(self) -> None:
        assert build_all_engineering_analytics_views(self.team) == []

    def test_gate_builds_only_present_views(self) -> None:
        self._create_table(
            "github_pull_requests", _PULL_REQUESTS_COLUMNS, [_pr_row(10, "alice", "open", 0, "2026-01-10 10:00:00")]
        )
        names = {view.name for view in build_all_engineering_analytics_views(self.team)}
        assert names == {"engineering_analytics_pull_requests"}

    def test_pull_requests_view_maps_columns(self) -> None:
        self._create_table(
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
            "FROM engineering_analytics_pull_requests ORDER BY number"
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
        self._create_table(
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
            "FROM engineering_analytics_workflow_runs ORDER BY id"
        )

        # completed runs carry a duration; in-progress run has null duration and null conclusion
        assert rows[0] == ("CI", "completed", "success", 1800, "PostHog", "posthog")
        assert rows[1][3] == 2700
        assert rows[2] == ("Deploy", "in_progress", None, None, "PostHog", "posthog")
