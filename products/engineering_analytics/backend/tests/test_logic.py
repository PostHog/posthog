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
from products.engineering_analytics.backend.facade.contracts import MetricQuality, PRLifecycleEventKind, PRState
from products.engineering_analytics.backend.logic import build_pr_lifecycle
from products.engineering_analytics.backend.tests.test_views import (
    _PULL_REQUESTS_COLUMNS,
    _WORKFLOW_RUNS_COLUMNS,
    _pr_row,
    _run_row,
)

_PR_LIFECYCLE = "products.engineering_analytics.backend.logic.queries.pr_lifecycle.execute_hogql_query"

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.logic"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _header(
    state: str,
    *,
    merged_at: datetime | None,
    closed_at: datetime | None = None,
    is_bot: bool = False,
    head_sha: str = "sha10",
) -> tuple:
    # Mirrors the SELECT column order in query_pr_lifecycle's header query.
    return (
        1010,
        10,
        "PR 10",
        state,
        False,
        _dt("2026-01-10T09:00:00"),
        merged_at,
        closed_at if closed_at is not None else merged_at,
        "alice",
        "https://avatars/alice",
        is_bot,
        "PostHog",
        "posthog",
        head_sha,
    )


class TestPRLifecycleMapping(BaseTest):
    """HogQL parsing (parse_select runs for real) plus row mapping and event
    assembly, without touching object storage."""

    def test_assembles_ordered_events_and_marks_partial(self) -> None:
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [("CI", "completed", "success", _dt("2026-01-11T09:00:00"), _dt("2026-01-11T12:00:00"))]
        with mock.patch(_PR_LIFECYCLE, side_effect=[_resp([header]), _resp(runs)]):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.metric_quality == MetricQuality.PARTIAL
        assert lifecycle.pull_request.state == PRState.MERGED
        assert lifecycle.pull_request.author.handle == "alice"
        assert lifecycle.pull_request.author.is_bot is False
        assert lifecycle.pull_request.repo.owner == "PostHog" and lifecycle.pull_request.repo.name == "posthog"
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_STARTED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]

    def test_returns_none_when_not_found(self) -> None:
        with mock.patch(_PR_LIFECYCLE, return_value=_resp([])):
            assert build_pr_lifecycle(team=self.team, pr_number=999, repo=None) is None

    def test_passes_through_view_derived_fields(self) -> None:
        # is_bot and state come from the view as columns; the logic layer does not re-derive them.
        header = _header("closed", merged_at=None, closed_at=_dt("2026-01-12T15:00:00"), is_bot=True, head_sha="")
        with mock.patch(_PR_LIFECYCLE, return_value=_resp([header])):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo=None)

        assert lifecycle is not None
        assert lifecycle.pull_request.state == PRState.CLOSED
        assert lifecycle.pull_request.author.is_bot is True
        assert [e.kind for e in lifecycle.events] == [PRLifecycleEventKind.OPENED, PRLifecycleEventKind.CLOSED]

    @parameterized.expand(
        [
            ("open", PRState.OPEN),
            ("closed", PRState.CLOSED),
            ("merged", PRState.MERGED),
        ]
    )
    def test_state_passthrough(self, state: str, expected: PRState) -> None:
        merged_at = _dt("2026-01-12T15:00:00") if state == "merged" else None
        with mock.patch(_PR_LIFECYCLE, return_value=_resp([_header(state, merged_at=merged_at, head_sha="")])):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo=None)

        assert lifecycle is not None
        assert lifecycle.pull_request.state == expected


class TestPRLifecycleWarehouse(ClickhouseTestMixin, BaseTest):
    """End-to-end through the read-layer views over real warehouse tables.
    Skips when object storage is unreachable."""

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
        assert lifecycle.pull_request.repo.name == "posthog"
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_STARTED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]
