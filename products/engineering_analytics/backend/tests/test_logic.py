import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

import pandas as pd
from parameterized import parameterized

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.engineering_analytics.backend.facade.contracts import (
    BucketKind,
    MetricQuality,
    PRLifecycleEventKind,
    PRState,
)
from products.engineering_analytics.backend.logic import build_pr_lifecycle, build_time_to_merge, build_workflow_report
from products.engineering_analytics.backend.logic.queries.pull_requests import is_bot_handle

_QUERIES = "products.engineering_analytics.backend.logic.queries"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class TestEngineeringAnalyticsLogicMapping(BaseTest):
    """Validates HogQL parsing (parse_select runs for real) plus row mapping,
    event assembly, and metric_quality — without touching object storage."""

    def test_workflow_report_maps_rows_and_marks_precise(self) -> None:
        rows = [
            ("CI", 2, 0.5, 2250.0, 2700.0, _dt("2026-01-22T10:45:00")),
            ("Deploy", 1, 0.0, 300.0, 300.0, None),
        ]
        with mock.patch(f"{_QUERIES}.workflow_runs.execute_hogql_query", return_value=_resp(rows)):
            report = build_workflow_report(team=self.team, date_from="-7d", date_to=None, repo="PostHog/posthog")

        assert report.metric_quality == MetricQuality.PRECISE
        assert report.date_from == "-7d"
        assert report.date_to is None
        assert report.repo is not None and report.repo.owner == "PostHog" and report.repo.name == "posthog"
        assert [(r.workflow_name, r.total_runs, r.success_rate) for r in report.rows] == [
            ("CI", 2, 0.5),
            ("Deploy", 1, 0.0),
        ]
        assert report.rows[0].last_failed_at == _dt("2026-01-22T10:45:00")
        assert report.rows[1].last_failed_at is None

    def test_time_to_merge_all_marks_coarse(self) -> None:
        with mock.patch(
            f"{_QUERIES}.pull_requests.execute_hogql_query", return_value=_resp([("all", 2, 216000.0, 259200.0)])
        ):
            result = build_time_to_merge(
                team=self.team, date_from="-7d", date_to=None, repo=None, group_by_author=False
            )

        assert result.metric_quality == MetricQuality.COARSE
        assert result.repo is None
        assert len(result.rows) == 1
        assert result.rows[0].bucket == "all"
        assert result.rows[0].bucket_kind == BucketKind.ALL
        assert result.rows[0].pr_count == 2

    def test_time_to_merge_by_author_sets_author_bucket_kind(self) -> None:
        rows = [("alice", 1, 172800.0, 172800.0), ("bob", 1, 259200.0, 259200.0)]
        with mock.patch(f"{_QUERIES}.pull_requests.execute_hogql_query", return_value=_resp(rows)):
            result = build_time_to_merge(team=self.team, date_from="-7d", date_to=None, repo=None, group_by_author=True)

        assert result.group_by_author is True
        assert {r.bucket for r in result.rows} == {"alice", "bob"}
        assert all(r.bucket_kind == BucketKind.AUTHOR for r in result.rows)

    def test_pr_lifecycle_assembles_ordered_events(self) -> None:
        header = [
            (
                1010,
                10,
                "PR 10",
                "closed",
                False,
                _dt("2026-01-10T09:00:00"),
                _dt("2026-01-12T15:00:00"),
                _dt("2026-01-12T15:00:00"),
                "alice",
                "https://avatars/alice",
                "sha10",
            )
        ]
        runs = [("CI", "completed", "success", _dt("2026-01-11T09:00:00"), _dt("2026-01-11T12:00:00"))]
        with mock.patch(
            f"{_QUERIES}.pull_requests.execute_hogql_query",
            side_effect=[_resp(header), _resp(runs)],
        ):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.metric_quality == MetricQuality.PARTIAL
        assert lifecycle.pull_request.state == PRState.MERGED
        assert lifecycle.pull_request.author.handle == "alice"
        assert lifecycle.pull_request.author.is_bot is False
        assert lifecycle.pull_request.repo.owner == "PostHog"
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_STARTED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]

    def test_pr_lifecycle_returns_none_when_not_found(self) -> None:
        with mock.patch(f"{_QUERIES}.pull_requests.execute_hogql_query", return_value=_resp([])):
            assert build_pr_lifecycle(team=self.team, pr_number=999, repo=None) is None

    @parameterized.expand(
        [
            ("open_pr", "open", None, PRState.OPEN),
            ("closed_pr", "closed", None, PRState.CLOSED),
            ("merged_pr", "closed", _dt("2026-01-12T15:00:00"), PRState.MERGED),
        ]
    )
    def test_pr_lifecycle_derives_state(
        self, _name: str, state: str, merged_at: datetime | None, expected: PRState
    ) -> None:
        header = [
            (
                1010,
                10,
                "PR 10",
                state,
                False,
                _dt("2026-01-10T09:00:00"),
                merged_at,
                merged_at,
                "alice",
                "https://avatars/alice",
                "",
            )
        ]
        with mock.patch(f"{_QUERIES}.pull_requests.execute_hogql_query", return_value=_resp(header)):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo=None)

        assert lifecycle is not None
        assert lifecycle.pull_request.state == expected

    @parameterized.expand(
        [
            ("dependabot[bot]", True),
            ("posthog-bot", True),
            ("renovate", True),
            ("alice", False),
            ("bob", False),
        ]
    )
    def test_is_bot_handle(self, handle: str, expected: bool) -> None:
        assert is_bot_handle(handle) is expected


TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics"

_WORKFLOW_RUNS_COLUMNS = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "run_started_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "updated_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
}

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
}


def _user(login: str) -> str:
    return f'{{"login": "{login}", "avatar_url": "https://avatars/{login}"}}'


def _run_row(
    run_id: int,
    name: str,
    head_sha: str,
    status: str,
    conclusion: str | None,
    run_started_at: str,
    updated_at: str,
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
    }


def _pr_row(
    number: int,
    login: str,
    state: str,
    draft: int,
    created_at: str,
    *,
    merged_at: str | None = None,
    head_sha: str = "",
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
    }


def _pull_request_rows() -> list[dict[str, Any]]:
    return [
        _pr_row(10, "alice", "closed", 0, "2026-01-10 10:00:00", merged_at="2026-01-12 10:00:00"),  # 2 days
        _pr_row(11, "bob", "closed", 0, "2026-01-12 10:00:00", merged_at="2026-01-15 10:00:00"),  # 3 days
        _pr_row(12, "charlie", "open", 0, "2026-01-08 10:00:00"),  # unmerged -> excluded
        _pr_row(13, "dependabot[bot]", "closed", 0, "2026-01-10 10:00:00", merged_at="2026-01-11 10:00:00"),  # bot
        _pr_row(14, "alice", "closed", 1, "2026-01-09 10:00:00", merged_at="2026-01-10 10:00:00"),  # draft
        _pr_row(15, "posthog-bot", "closed", 0, "2026-01-09 10:00:00", merged_at="2026-01-10 10:00:00"),  # allowlist
    ]


class TestEngineeringAnalyticsLogicWarehouse(ClickhouseTestMixin, BaseTest):
    """End-to-end against real warehouse tables. Skips when object storage is
    unreachable so the suite still runs without the dev stack."""

    def setUp(self) -> None:
        super().setUp()
        self._cleanups: list = []
        self._tmpfiles: list[str] = []

    def tearDown(self) -> None:
        for cleanup in self._cleanups:
            cleanup()
        for path in self._tmpfiles:
            Path(path).unlink(missing_ok=True)
        super().tearDown()

    def _create_table(self, name: str, columns: dict, rows: list[dict[str, Any]]) -> None:
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self._tmpfiles.append(tmp.name)
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
        self._cleanups.append(cleanup)

    @freeze_time("2026-02-01")
    def test_workflow_report_aggregates_and_orders_by_median(self) -> None:
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(1001, "CI", "sha1", "completed", "success", "2026-01-20 10:00:00", "2026-01-20 10:30:00"),
                _run_row(1002, "CI", "sha2", "completed", "failure", "2026-01-22 10:00:00", "2026-01-22 10:45:00"),
                _run_row(1003, "Deploy", "sha3", "in_progress", None, "2026-01-25 10:00:00", "2026-01-25 10:05:00"),
            ],
        )

        report = build_workflow_report(team=self.team, date_from="-60d", date_to=None, repo=None)

        assert [r.workflow_name for r in report.rows] == ["CI", "Deploy"]
        ci, deploy = report.rows
        assert ci.total_runs == 2
        assert ci.success_rate == 0.5
        assert ci.median_duration_seconds == 2250
        assert ci.last_failed_at is not None and ci.last_failed_at.isoformat().startswith("2026-01-22T10:45")
        assert deploy.total_runs == 1
        assert deploy.success_rate == 0.0
        assert deploy.median_duration_seconds == 300
        assert deploy.last_failed_at is None

    @freeze_time("2026-02-01")
    def test_time_to_merge_all_excludes_bots_drafts_and_unmerged(self) -> None:
        self._create_table("github_pull_requests", _PULL_REQUESTS_COLUMNS, _pull_request_rows())

        result = build_time_to_merge(team=self.team, date_from="-60d", date_to=None, repo=None, group_by_author=False)

        assert len(result.rows) == 1
        assert result.rows[0].bucket == "all"
        assert result.rows[0].pr_count == 2  # alice + bob; bot, draft, unmerged excluded
        assert result.rows[0].median_seconds == 216000

    @freeze_time("2026-02-01")
    def test_time_to_merge_by_author(self) -> None:
        self._create_table("github_pull_requests", _PULL_REQUESTS_COLUMNS, _pull_request_rows())

        result = build_time_to_merge(team=self.team, date_from="-60d", date_to=None, repo=None, group_by_author=True)

        by_bucket = {r.bucket: r for r in result.rows}
        assert set(by_bucket) == {"alice", "bob"}
        assert by_bucket["alice"].median_seconds == 172800
        assert by_bucket["bob"].median_seconds == 259200

    @freeze_time("2026-02-01")
    def test_pr_lifecycle_end_to_end(self) -> None:
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    10, "alice", "closed", 0, "2026-01-10 09:00:00", merged_at="2026-01-12 15:00:00", head_sha="sha10"
                )
            ],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(2001, "CI", "sha10", "completed", "success", "2026-01-11 09:00:00", "2026-01-11 12:00:00")],
        )

        lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.pull_request.state == PRState.MERGED
        assert lifecycle.pull_request.author.handle == "alice"
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_STARTED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]
