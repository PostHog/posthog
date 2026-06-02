import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from django.utils import timezone

import pandas as pd
from parameterized import parameterized

from posthog.hogql.errors import QueryError

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import (
    GitHubSourceNotConnectedError,
    MetricQuality,
    PRLifecycleEventKind,
    PRState,
)
from products.engineering_analytics.backend.logic import (
    build_ci_cards,
    build_pr_lifecycle,
    build_pull_request_list,
    build_workflow_health,
)
from products.engineering_analytics.backend.logic.queries import _curated
from products.engineering_analytics.backend.tests.test_views import (
    _PULL_REQUESTS_COLUMNS,
    _WORKFLOW_RUNS_COLUMNS,
    _pr_row,
    _run_row,
)

# All query modules run through this helper; patch it to test row mapping without a warehouse.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.run_query"

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.logic"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _ago(days: int) -> str:
    # Seed dates relative to real time: HogQL now() runs server-side and ignores
    # freezegun, so window/age assertions must share the clock the query uses.
    return (timezone.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


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


class _WarehouseMixin(ClickhouseTestMixin):
    """Creates warehouse tables from in-memory rows; skips when object storage is
    unreachable so the suite still runs without the dev stack."""

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


class TestPRLifecycleMapping(BaseTest):
    """HogQL parsing (parse_select runs for real) plus row mapping and event
    assembly, without touching object storage."""

    def test_assembles_ordered_events_and_marks_partial(self) -> None:
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [("CI", "completed", "success", _dt("2026-01-11T09:00:00"), _dt("2026-01-11T12:00:00"))]
        with mock.patch(_RUN_QUERY, side_effect=[_resp([header]), _resp(runs)]):
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
        with mock.patch(_RUN_QUERY, return_value=_resp([])):
            assert build_pr_lifecycle(team=self.team, pr_number=999, repo=None) is None

    def test_passes_through_view_derived_fields(self) -> None:
        # is_bot and state come from the curated query as columns; the logic layer does not re-derive them.
        header = _header("closed", merged_at=None, closed_at=_dt("2026-01-12T15:00:00"), is_bot=True, head_sha="")
        with mock.patch(_RUN_QUERY, return_value=_resp([header])):
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
        with mock.patch(_RUN_QUERY, return_value=_resp([_header(state, merged_at=merged_at, head_sha="")])):
            lifecycle = build_pr_lifecycle(team=self.team, pr_number=10, repo=None)

        assert lifecycle is not None
        assert lifecycle.pull_request.state == expected


class TestEndpointMapping(BaseTest):
    """Row mapping for the aggregate endpoints (query helper mocked, no warehouse),
    plus the no-source error path."""

    def test_ci_cards_maps_counts(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([(5, 2, 1, 1)])):
            cards = build_ci_cards(team=self.team)
        assert (cards.open_prs, cards.repos, cards.stuck, cards.failing_ci) == (5, 2, 1, 1)

    def test_pull_request_list_maps_row(self) -> None:
        row = (
            10,
            "PR 10",
            "PostHog",
            "posthog",
            "alice",
            "https://avatars/alice",
            False,
            "open",
            False,
            _dt("2026-01-10T09:00:00"),
            None,
            None,
            ["bug", "p1"],
            3,
            2,
            1,
            0,
        )
        with mock.patch(_RUN_QUERY, return_value=_resp([row])):
            items = build_pull_request_list(team=self.team, date_from="-30d")

        assert len(items) == 1
        item = items[0]
        assert item.number == 10
        assert item.author.handle == "alice" and item.author.is_bot is False
        assert item.repo.owner == "PostHog" and item.repo.name == "posthog"
        assert item.state == PRState.OPEN
        assert item.labels == ["bug", "p1"]
        assert item.open_to_merge_seconds is None
        assert (item.ci.runs, item.ci.passing, item.ci.failing, item.ci.pending) == (3, 2, 1, 0)

    def test_workflow_health_maps_and_nulls_empty_window(self) -> None:
        rows = [
            ("CI", 10, 0.9, 120.0, 600.0, _dt("2026-01-20T00:00:00")),
            # No completed runs: success_rate is NULL and quantileIf returns NaN — both map to None.
            ("Deploy", 2, None, float("nan"), float("nan"), None),
        ]
        with mock.patch(_RUN_QUERY, return_value=_resp(rows)):
            items = build_workflow_health(team=self.team, date_from="-30d", date_to=None)

        assert items[0].workflow_name == "CI" and items[0].success_rate == 0.9
        assert items[0].p50_seconds == 120.0 and items[0].p95_seconds == 600.0
        assert items[1].success_rate is None
        assert items[1].p50_seconds is None and items[1].p95_seconds is None
        assert items[1].last_failure_at is None

    def test_run_query_translates_unknown_table_to_source_error(self) -> None:
        with mock.patch(
            "products.engineering_analytics.backend.logic.queries._curated.execute_hogql_query",
            side_effect=QueryError("Unknown table `github_pull_requests`."),
        ):
            with self.assertRaises(GitHubSourceNotConnectedError):
                _curated.run_query("SELECT 1", team=self.team, query_type="engineering_analytics.test")

    def test_build_propagates_source_error(self) -> None:
        with mock.patch(_RUN_QUERY, side_effect=GitHubSourceNotConnectedError()):
            with self.assertRaises(GitHubSourceNotConnectedError):
                build_pull_request_list(team=self.team)


class TestPRLifecycleWarehouse(_WarehouseMixin, BaseTest):
    """End-to-end through the curated builders over real warehouse tables.
    Skips when object storage is unreachable."""

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


class TestEndpointsWarehouse(_WarehouseMixin, BaseTest):
    """End-to-end aggregates over real warehouse tables. Seeds dates relative to
    real time (HogQL now() is server-side). Skips when object storage is
    unreachable."""

    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                # open, recent (<7d), human, failing CI on sha10
                _pr_row(10, "alice", "open", 0, _ago(1), head_sha="sha10", labels=("bug",)),
                # open, old (>7d), human -> stuck; passing CI on sha11
                _pr_row(11, "bob", "open", 0, _ago(30), head_sha="sha11"),
                # open draft -> not stuck
                _pr_row(12, "carol", "open", 1, _ago(30), head_sha="sha12"),
                # open bot -> not stuck
                _pr_row(13, "dependabot[bot]", "open", 0, _ago(30), head_sha="sha13"),
                # merged within the default 30d window -> in the list, not open
                _pr_row(14, "alice", "closed", 0, _ago(40), merged_at=_ago(5), head_sha="sha14"),
                # merged long ago -> outside the window, excluded from the list
                _pr_row(15, "alice", "closed", 0, _ago(120), merged_at=_ago(60), head_sha="sha15"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(2001, "CI", "sha10", "completed", "failure", _ago(1), _ago(1)),
                _run_row(2002, "CI", "sha11", "completed", "success", _ago(2), _ago(2)),
            ],
        )

    def test_ci_cards_counts(self) -> None:
        self._seed()
        cards = api.get_ci_cards(team=self.team)
        assert cards.open_prs == 4  # 10, 11, 12, 13
        assert cards.repos == 1  # all PostHog/posthog
        assert cards.stuck == 1  # only 11 (10 recent, 12 draft, 13 bot)
        assert cards.failing_ci == 1  # only 10 has a failing latest run

    def test_pull_request_list_window_and_rollup(self) -> None:
        self._seed()
        items = api.list_pull_requests(team=self.team)
        by_number = {item.number: item for item in items}
        assert set(by_number) == {10, 11, 12, 13, 14}  # 15 merged before the window
        assert by_number[10].ci.failing == 1
        assert by_number[11].ci.passing == 1
        assert by_number[13].author.is_bot is True

    def test_workflow_health_aggregates(self) -> None:
        self._seed()
        items = api.list_workflow_health(team=self.team)
        ci = next(item for item in items if item.workflow_name == "CI")
        assert ci.run_count == 2
        assert ci.success_rate == 0.5  # 1 success of 2 completed
        assert ci.last_failure_at is not None
