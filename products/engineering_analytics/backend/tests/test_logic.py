import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

import pandas as pd
from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import (
    GitHubSource,
    GitHubSourceNotConnectedError,
    MetricQuality,
    PRLifecycleEventKind,
    PRState,
)
from products.engineering_analytics.backend.logic import build_workflow_health
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_cost import query_cost_per_merge_series
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
    list_github_sources,
    resolve_github_tables,
)
from products.engineering_analytics.backend.logic.views.source_schema import WORKFLOW_JOBS_COLUMNS
from products.engineering_analytics.backend.tests.test_views import (
    _PULL_REQUESTS_COLUMNS,
    _WORKFLOW_RUNS_COLUMNS,
    GITHUB_SOURCE_PREFIX,
    _pr_row,
    _run_row,
    connect_github_source_without_data,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

# Every query module runs HogQL through this method; patch it to test row mapping without a
# warehouse. Patching the unbound method means the mock is called without `self`, so a plain
# return_value / side_effect works as before.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"
_PR_LIST = "products.engineering_analytics.backend.logic.queries.pull_request_list"

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.logic"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _ago(days: int) -> str:
    # Seed dates relative to real time: HogQL now() runs server-side and ignores
    # freezegun, so window/age assertions must share the clock the query uses.
    return (timezone.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _job_row(
    job_id: int,
    run_id: int,
    name: str,
    conclusion: str,
    *,
    run_attempt: int = 1,
    labels: str = '["depot-ubuntu-22.04-4"]',
    started: str = "2026-01-01 00:00:00",
    completed: str = "2026-01-01 00:02:00",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "name": name,
        "workflow_name": "CI",
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": "sha60",
        "head_branch": "main",
        "labels": labels,
        "runner_name": "runner-1",
        "runner_group_name": "depot",
        "created_at": started,
        "started_at": started,
        "completed_at": completed,
        "steps": "[]",
    }


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


class _WarehouseMixin(ClickhouseTestMixin, BaseTest):
    """Seeds warehouse tables behind a connected GitHub source with a non-default prefix,
    so the full resolve -> build -> query path runs end to end against `myprefixgithub_*`
    tables. Skips when object storage is unreachable so the suite still runs without the
    dev stack."""

    def setUp(self) -> None:
        super().setUp()
        self._github_source: ExternalDataSource | None = None

    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> None:
        if self._github_source is None:
            self._github_source = create_github_source(self.team)
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
                source=self._github_source,
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        # base_name is "github_<endpoint>"; the synced schema/endpoint is its suffix.
        link_schema(self.team, self._github_source, name=base_name.removeprefix("github_"), table=table)


class TestPRLifecycleMapping(BaseTest):
    """HogQL parsing (parse_select runs for real) plus row mapping and event
    assembly, without touching object storage. The query helper is mocked, so a GitHub
    source is connected (ORM only) just to satisfy the resolver."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_assembles_ordered_events_and_marks_partial(self) -> None:
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [(2001, "CI", "completed", "success", _dt("2026-01-11T09:00:00"), _dt("2026-01-11T12:00:00"))]
        with mock.patch(_RUN_QUERY, side_effect=[_resp([header]), _resp(runs)]):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

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
        assert [e.run_id for e in lifecycle.events] == [None, 2001, 2001, None]

    def test_skips_events_with_null_timestamps(self) -> None:
        # parseDateTimeBestEffort yields NULL on a malformed/missing timestamp, so an event's `at`
        # can come back None. A single bad run timestamp must drop just that event, not raise and
        # take down the whole PR's lifecycle (the contract's `at` is non-nullable, and the event
        # sort can't order a None key).
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [
            # null start -> CI_STARTED dropped, but the completed finish still lands
            (2001, "CI", "completed", "success", None, _dt("2026-01-11T12:00:00")),
            # both timestamps null -> both events dropped
            (2002, "Deploy", "completed", "success", None, None),
        ]
        with mock.patch(_RUN_QUERY, side_effect=[_resp([header]), _resp(runs)]):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]
        assert [e.run_id for e in lifecycle.events] == [None, 2001, None]

    def test_returns_none_when_not_found(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([])):
            assert api.get_pr_lifecycle(team=self.team, pr_number=999, repo="PostHog/posthog") is None

    @parameterized.expand(["PostHog", "PostHog/", "/posthog", "/"])
    def test_malformed_repo_raises_before_querying(self, repo: str) -> None:
        # A half-specified repo must fail loudly, not silently drop the filter and
        # return a PR from the wrong repo. Raises in _split_repo before any query.
        with self.assertRaises(ValueError):
            api.get_pr_lifecycle(team=self.team, pr_number=10, repo=repo)

    def test_passes_through_view_derived_fields(self) -> None:
        # is_bot and state come from the curated query as columns; the logic layer does not re-derive them.
        header = _header("closed", merged_at=None, closed_at=_dt("2026-01-12T15:00:00"), is_bot=True, head_sha="")
        with mock.patch(_RUN_QUERY, return_value=_resp([header])):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.pull_request.state == PRState.CLOSED
        assert lifecycle.pull_request.author.is_bot is True
        assert [e.kind for e in lifecycle.events] == [PRLifecycleEventKind.OPENED, PRLifecycleEventKind.CLOSED]


class TestEndpointMapping(BaseTest):
    """Row mapping for the aggregate endpoints (the query method mocked, no warehouse).
    A GitHub source is connected (ORM only) so the resolver succeeds before the mocked
    query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_ci_cards_maps_counts(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([(5, 2, 1, 1)])):
            cards = api.get_ci_cards(team=self.team)
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
            ["E2E CI"],
            5,
            2,
        )
        with mock.patch(_RUN_QUERY, return_value=_resp([row])):
            result = api.list_pull_requests(team=self.team, date_from="-30d")

        assert result.truncated is False
        assert len(result.items) == 1
        item = result.items[0]
        assert item.number == 10
        assert item.author.handle == "alice" and item.author.is_bot is False
        assert item.repo.owner == "PostHog" and item.repo.name == "posthog"
        assert item.state == PRState.OPEN
        assert item.labels == ["bug", "p1"]
        assert item.open_to_merge_seconds is None
        assert (item.ci.runs, item.ci.passing, item.ci.failing, item.ci.pending) == (3, 2, 1, 0)
        assert item.ci.failing_workflows == ["E2E CI"]
        assert (item.pushes, item.rerun_cycles) == (5, 2)
        assert item.estimated_cost_usd is None

    def test_pull_request_list_flags_truncation(self) -> None:
        # Cap patched low; return more rows than the cap to exercise the N+1 overflow
        # detection — the list reports truncated instead of silently dropping the tail.
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
            ["bug"],
            0,
            0,
            0,
            0,
            list[str](),
            0,
            0,
        )
        with mock.patch(f"{_PR_LIST}._LIMIT", 2), mock.patch(_RUN_QUERY, return_value=_resp([row, row, row])):
            result = api.list_pull_requests(team=self.team, date_from="-30d")

        assert result.truncated is True
        assert result.limit == 2
        assert len(result.items) == 2

    def test_workflow_health_maps_and_nulls_empty_window(self) -> None:
        # Columns: owner, name, workflow, run_count, success_rate, p50, p95, last_failure_at,
        # completed_count, latest_failed, latest_conclusion, rerun_cycles.
        rows = [
            ("PostHog", "posthog", "CI", 10, 0.9, 120.0, 600.0, _dt("2026-01-20T00:00:00"), 8, 0, "success", 3),
            # No completed runs: success_rate is NULL and quantileIf returns NaN — both map to None,
            # latest_run_failed is None (the completed_count guard), and latest_run_conclusion is None too
            # despite argMaxIf's '' default.
            ("PostHog", "posthog", "Deploy", 2, None, float("nan"), float("nan"), None, 0, 0, "", 0),
        ]
        # A -30d window buckets by day. Must land inside the window (relative to now). Columns:
        # owner, name, workflow, bucket_start, run_count, completed, successes, failures.
        bucket_rows = [("PostHog", "posthog", "CI", datetime.now(tz=UTC) - timedelta(days=1), 10, 8, 7, 1)]
        # Third response: the previous-window success rate (the Δ baseline); Deploy had no prior runs.
        prev_rows = [("PostHog", "posthog", "CI", 0.95)]
        with mock.patch(_RUN_QUERY, side_effect=[_resp(rows), _resp(bucket_rows), _resp(prev_rows)]):
            items = api.list_workflow_health(team=self.team, date_from="-30d", date_to=None)

        assert items[0].workflow_name == "CI" and items[0].success_rate == 0.9
        assert items[0].repo.owner == "PostHog" and items[0].repo.name == "posthog"
        assert items[0].granularity == "day"
        assert items[0].latest_run_failed is False
        assert items[0].latest_run_conclusion == "success"
        assert items[0].rerun_cycles == 3
        assert items[0].success_rate_prev == 0.95
        assert items[1].success_rate_prev is None
        # The series spans the whole window, zero-filled except the bucket with runs.
        assert len(items[0].buckets) >= 30
        seeded_bucket = next(entry for entry in items[0].buckets if entry.run_count > 0)
        assert (seeded_bucket.completed, seeded_bucket.successes, seeded_bucket.failures) == (8, 7, 1)
        assert all(entry.run_count == 0 for entry in items[1].buckets)
        assert items[0].p50_seconds == 120.0 and items[0].p95_seconds == 600.0
        assert items[1].success_rate is None
        assert items[1].latest_run_failed is None
        assert items[1].latest_run_conclusion is None
        assert items[1].p50_seconds is None and items[1].p95_seconds is None
        assert items[1].last_failure_at is None


class TestResolveBranchMapping(BaseTest):
    """Row mapping for resolve_branch (query method mocked, no warehouse). A GitHub source is
    connected (ORM only) so the resolver succeeds before the mocked query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_maps_rows_and_normalizes_empty_fields(self) -> None:
        # branch columns: repo_owner, repo_name, number, title, state. The second row carries an empty
        # title / null state -> both normalize to None.
        rows = [("PostHog", "posthog", 42, "Fix bug", "merged"), ("PostHog", "posthog", 7, "", None)]
        with mock.patch(_RUN_QUERY, return_value=_resp(rows)) as run:
            matches = api.resolve_branch(team=self.team, branch="feat/x")
        assert [(m.repo, m.number, m.title, m.state) for m in matches] == [
            ("PostHog/posthog", 42, "Fix bug", "merged"),
            ("PostHog/posthog", 7, None, None),
        ]
        assert run.call_count == 1

    @parameterized.expand([("branch_none", None), ("branch_blank", "   ")])
    def test_rejects_missing_branch(self, _name: str, branch: str | None) -> None:
        # Validation raises before any query is issued (source resolution still succeeds first).
        with mock.patch(_RUN_QUERY) as run, self.assertRaises(ValueError):
            api.resolve_branch(team=self.team, branch=branch)
        run.assert_not_called()


class TestCostPerMergeSeries(BaseTest):
    """The cost-per-merged-PR trend on the repo hub: bucketing, zero-fill, and the cost/merge
    division guard. The two warehouse scans are mocked (curated fully faked), so this tests the
    Python fold — the runner-tier cost model, the bucket join, the empty-bucket handling — without
    a warehouse. The tier multiplier stays server-side; only group columns cross the mock boundary."""

    @staticmethod
    def _curated(cost_rows: list[tuple], merges_rows: list[tuple], *, jobs_synced: bool = True) -> mock.Mock:
        curated = mock.Mock()
        curated.jobs_source.return_value = "px_github_workflow_jobs" if jobs_synced else None
        curated.run_source.return_value = "px_github_workflow_runs"
        curated.pr_source.return_value = "px_github_pull_requests"
        # Cost scan first, then the merges scan — the call order in query_cost_per_merge_series.
        curated.run.side_effect = [_resp(cost_rows), _resp(merges_rows)]
        return curated

    def test_buckets_cost_per_merge_and_zero_fills(self) -> None:
        date_from = _dt("2026-06-01T00:00:00")
        date_to = _dt("2026-06-30T00:00:00")  # 29-day window -> day granularity, deterministic buckets.
        # Columns: bucket_start, labels, finished, elapsed, unfinished. depot-4 (4-core) bills at 2x, so
        # 2 min -> 2 * 0.004 * 2 = 0.016; 1 min -> 0.008.
        cost_rows = [
            (datetime(2026, 6, 2), '["depot-ubuntu-22.04-4"]', 1, 120.0, 0),
            (datetime(2026, 6, 3), '["depot-ubuntu-22.04-4"]', 1, 60.0, 0),
            (datetime(2026, 6, 6), '["depot-ubuntu-22.04-4"]', 1, 120.0, 0),  # cost but no merges below
        ]
        # Columns: bucket_start, merges.
        merges_rows = [
            (datetime(2026, 6, 2), 4),
            (datetime(2026, 6, 3), 2),
            (datetime(2026, 6, 5), 3),  # merges but no cost above
        ]
        granularity, buckets = query_cost_per_merge_series(
            curated=self._curated(cost_rows, merges_rows), date_from=date_from, date_to=date_to
        )

        assert granularity == "day"
        assert len(buckets) == 30  # June 1..30 inclusive, zero-filled.
        by_day = {bucket.bucket_start: bucket for bucket in buckets}

        # estimated_cost_usd / merges stay bucket-local; the ratio is the trailing 7-day rolling window.
        assert by_day[datetime(2026, 6, 2)].estimated_cost_usd == pytest.approx(0.016)
        assert by_day[datetime(2026, 6, 2)].merges == 4
        assert by_day[datetime(2026, 6, 2)].cost_per_merge_usd == pytest.approx(0.016 / 4)
        assert by_day[datetime(2026, 6, 3)].cost_per_merge_usd == pytest.approx((0.016 + 0.008) / 6)

        # A merge-only day still gets a ratio from the trailing window's cost.
        assert by_day[datetime(2026, 6, 5)].estimated_cost_usd is None
        assert by_day[datetime(2026, 6, 5)].merges == 3
        assert by_day[datetime(2026, 6, 5)].cost_per_merge_usd == pytest.approx((0.016 + 0.008) / 9)

        # A cost-only day likewise divides by the trailing window's merges (no divide-by-zero hole).
        assert by_day[datetime(2026, 6, 6)].estimated_cost_usd == pytest.approx(0.016)
        assert by_day[datetime(2026, 6, 6)].merges == 0
        assert by_day[datetime(2026, 6, 6)].cost_per_merge_usd == pytest.approx((0.016 + 0.008 + 0.016) / 9)

        # Once the trailing window slides past the merges (Jun 5 + 7d), cost alone yields no ratio.
        assert by_day[datetime(2026, 6, 12)].cost_per_merge_usd is None

        # An untouched bucket keeps its raw fields zero-filled but inherits the trailing ratio while
        # the window still covers data (Jun 10 window = Jun 4..10: Jun 6 cost / Jun 5 merges).
        empty = by_day[datetime(2026, 6, 10)]
        assert (empty.estimated_cost_usd, empty.merges) == (None, 0)
        assert empty.cost_per_merge_usd == pytest.approx(0.016 / 3)

        # A bucket whose whole trailing window is empty is fully null.
        dead = by_day[datetime(2026, 6, 20)]
        assert (dead.estimated_cost_usd, dead.merges, dead.cost_per_merge_usd) == (None, 0, None)

    def test_empty_when_jobs_source_unsynced(self) -> None:
        curated = self._curated([], [], jobs_synced=False)
        granularity, buckets = query_cost_per_merge_series(
            curated=curated, date_from=_dt("2026-06-01T00:00:00"), date_to=_dt("2026-06-30T00:00:00")
        )
        assert granularity == "day"
        assert buckets == []
        curated.run.assert_not_called()  # no jobs source -> no scan is issued


class TestResolveGitHubTables(BaseTest):
    """The per-team table resolver over the warehouse models (ORM only, no object storage).
    No source is connected in setUp so the missing-source path can be exercised."""

    def _connect(
        self,
        *,
        prefix: str,
        schemas: list[tuple[str, bool, bool]],
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
        team: Team | None = None,
    ) -> ExternalDataSource:
        # schemas: (endpoint name, should_sync, has a backing table)
        team = team or self.team
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
        )
        for name, should_sync, has_table in schemas:
            table = (
                create_warehouse_table_row(team, name=f"{prefix}github_{name}", source=source) if has_table else None
            )
            link_schema(team, source, name=name, table=table, should_sync=should_sync)
        return source

    _BOTH_SYNCED = [(PULL_REQUESTS_SCHEMA, True, True), (WORKFLOW_RUNS_SCHEMA, True, True)]

    def test_resolves_non_default_prefix_tables(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="myprefixgithub_pull_requests", workflow_runs="myprefixgithub_workflow_runs"
        )

    def test_raises_without_a_github_source(self) -> None:
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_build_raises_without_a_github_source(self) -> None:
        # The orchestrator surfaces the resolver's error so the viewset can map it to a 400.
        with self.assertRaises(GitHubSourceNotConnectedError):
            api.get_ci_cards(team=self.team)

    @parameterized.expand(
        [
            # Same-named schemas on a non-GitHub source must not be mistaken for a GitHub source.
            ("non_github_source", [(PULL_REQUESTS_SCHEMA, True, True), (WORKFLOW_RUNS_SCHEMA, True, True)], "stripe"),
            ("endpoint_not_synced", [(PULL_REQUESTS_SCHEMA, False, True), (WORKFLOW_RUNS_SCHEMA, False, True)], "gh"),
            ("missing_one_endpoint", [(PULL_REQUESTS_SCHEMA, True, True)], "gh"),
            ("schema_without_table", [(PULL_REQUESTS_SCHEMA, True, False), (WORKFLOW_RUNS_SCHEMA, True, False)], "gh"),
        ]
    )
    def test_raises_when_endpoints_unavailable(
        self, _name: str, schemas: list[tuple[str, bool, bool]], kind: str
    ) -> None:
        source_type = ExternalDataSourceType.STRIPE if kind == "stripe" else ExternalDataSourceType.GITHUB
        self._connect(prefix="myprefix", schemas=schemas, source_type=source_type)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_prefers_oldest_complete_source(self) -> None:
        # Two fully-connected GitHub sources (e.g. one per repo): the oldest wins, deterministically.
        self._connect(prefix="older", schemas=self._BOTH_SYNCED)
        self._connect(prefix="newer", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables.pull_requests == "oldergithub_pull_requests"

    def test_skips_incomplete_source_for_a_complete_one(self) -> None:
        # The oldest source is missing an endpoint; resolution falls through to the complete one.
        self._connect(prefix="incomplete", schemas=[(PULL_REQUESTS_SCHEMA, True, True)])
        self._connect(prefix="complete", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="completegithub_pull_requests", workflow_runs="completegithub_workflow_runs"
        )

    def test_ignores_soft_deleted_source(self) -> None:
        source = self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        ExternalDataSource.objects.filter(pk=source.pk).update(deleted=True)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_source_id_selects_a_specific_source(self) -> None:
        self._connect(prefix="older", schemas=self._BOTH_SYNCED)
        newer = self._connect(prefix="newer", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team, source_id=str(newer.id))
        assert tables == GitHubTables(
            pull_requests="newergithub_pull_requests", workflow_runs="newergithub_workflow_runs"
        )

    def test_unknown_source_id_raises(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id="0192f000-0000-7000-8000-000000000000")

    def test_malformed_source_id_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_github_tables(team=self.team, source_id="not-a-uuid")

    def test_source_id_is_scoped_to_the_team(self) -> None:
        # Selecting another team's source id must not leak it — the team filter excludes it.
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_source = self._connect(prefix="other", schemas=self._BOTH_SYNCED, team=other_team)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id=str(other_source.id))


class TestListGitHubSources(BaseTest):
    """list_github_sources lists every connected GitHub source for a picker (ORM only).
    Unlike resolve_github_tables it does not require synced tables — a half-synced source the
    user connected should still be selectable; the empty state handles an unusable pick."""

    def _source(
        self,
        *,
        prefix: str,
        repository: str | None = None,
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
        team: Team | None = None,
    ) -> ExternalDataSource:
        team = team or self.team
        return ExternalDataSource.objects.create(
            team=team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
            job_inputs={"repository": repository} if repository else {},
        )

    def test_lists_sources_oldest_first_with_repo_and_prefix(self) -> None:
        older = self._source(prefix="older", repository="PostHog/posthog")
        newer = self._source(prefix="newer", repository="PostHog/posthog.com")
        assert list_github_sources(team=self.team) == [
            GitHubSource(id=str(older.id), repo="PostHog/posthog", prefix="older"),
            GitHubSource(id=str(newer.id), repo="PostHog/posthog.com", prefix="newer"),
        ]

    def test_includes_sources_without_synced_tables(self) -> None:
        # No schemas/tables linked: resolve_github_tables would reject this, the picker keeps it.
        source = self._source(prefix="pronly", repository="PostHog/posthog")
        assert [s.id for s in list_github_sources(team=self.team)] == [str(source.id)]

    def test_repo_is_blank_without_a_repository_input(self) -> None:
        source = self._source(prefix="noinputs")
        assert list_github_sources(team=self.team) == [GitHubSource(id=str(source.id), repo="", prefix="noinputs")]

    def test_excludes_non_github_and_soft_deleted_sources(self) -> None:
        self._source(prefix="stripe", source_type=ExternalDataSourceType.STRIPE)
        deleted = self._source(prefix="gone", repository="PostHog/posthog")
        ExternalDataSource.objects.filter(pk=deleted.pk).update(deleted=True)
        kept = self._source(prefix="kept", repository="PostHog/posthog")
        assert [s.id for s in list_github_sources(team=self.team)] == [str(kept.id)]

    def test_empty_without_a_github_source(self) -> None:
        assert list_github_sources(team=self.team) == []

    def test_scoped_to_the_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._source(prefix="theirs", repository="PostHog/posthog", team=other_team)
        assert list_github_sources(team=self.team) == []


class TestWorkflowHealthWindowCap(BaseTest):
    @parameterized.expand(["2000-01-01", "-500d"])
    def test_rejects_windows_beyond_a_year(self, date_from: str) -> None:
        # The window cap is build_workflow_health's own guard, reached before it reads any data; a
        # handle with dummy table names exposes the team (for timezone) and nothing else is touched.
        curated = CuratedGitHubSource(team=self.team, tables=GitHubTables(pull_requests="pr", workflow_runs="wr"))
        with pytest.raises(ValueError, match="the maximum is 366"):
            build_workflow_health(curated=curated, date_from=date_from)


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
                # open allowlisted bot (no [bot] suffix) -> is_bot, not stuck
                _pr_row(16, "renovate", "open", 0, _ago(30), head_sha="sha16"),
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
                _run_row(2001, "CI", "sha10", "completed", "failure", _ago(1), _ago(1), pr_number=10),
                _run_row(2002, "CI", "sha11", "completed", "success", _ago(2), _ago(2), pr_number=11),
                # A second push on PR 10 (new head SHA) that was re-run -> pushes=2, rerun_cycles=1.
                # A non-CI workflow so the CI workflow-health assertions stay at 2 runs.
                _run_row(
                    2003, "Deploy", "sha10b", "completed", "success", _ago(1), _ago(1), pr_number=10, run_attempt=2
                ),
            ],
        )

    def test_ci_cards_counts(self) -> None:
        self._seed()
        cards = api.get_ci_cards(team=self.team)
        assert cards.open_prs == 5  # 10, 11, 12, 13, 16
        assert cards.repos == 1  # all PostHog/posthog
        assert cards.stuck == 1  # only 11 (10 recent, 12 draft, 13 and 16 bots)
        assert cards.failing_ci == 1  # only 10 has a failing latest run

    def test_pull_request_list_window_and_rollup(self) -> None:
        self._seed()
        result = api.list_pull_requests(team=self.team)
        assert result.truncated is False
        by_number = {item.number: item for item in result.items}
        assert set(by_number) == {10, 11, 12, 13, 14, 16}  # 15 merged before the window
        assert by_number[10].ci.failing == 1
        assert by_number[11].ci.passing == 1
        assert by_number[13].author.is_bot is True  # '[bot]' suffix branch
        assert by_number[16].author.is_bot is True  # KNOWN_BOT_HANDLES allowlist branch
        # pushes = distinct head SHAs across runs attributed to the PR; rerun_cycles = 2nd+ attempts.
        assert (by_number[10].pushes, by_number[10].rerun_cycles) == (2, 1)
        assert (by_number[11].pushes, by_number[11].rerun_cycles) == (1, 0)
        assert by_number[12].pushes == 0  # no runs attributed to this PR
        assert by_number[10].estimated_cost_usd is None  # no jobs source seeded here → no cost figure

    def test_pull_request_list_includes_cost_when_jobs_synced(self) -> None:
        # With the jobs source synced, the list carries per-PR cost + billable minutes.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(70, "alice", "open", 0, _ago(1), head_sha="sha70")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9400, "CI", "sha70", "completed", "success", _ago(1), _ago(1), pr_number=70)],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [_job_row(94000, 9400, "build", "success", labels='["depot-ubuntu-22.04-4"]')],
        )
        item = next(i for i in api.list_pull_requests(team=self.team).items if i.number == 70)
        assert item.estimated_cost_usd is not None and item.estimated_cost_usd > 0
        assert item.billable_minutes is not None and item.billable_minutes > 0

    def test_pr_cost_sums_all_jobs_past_the_default_row_cap(self) -> None:
        # A PR with more jobs than HogQL's default 100-row cap: the detail cost must sum every job, not
        # silently truncate to the first 100 (the truncation that made PR detail cost disagree with the list).
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(71, "alice", "open", 0, _ago(1), head_sha="sha71")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9700, "CI", "sha71", "completed", "success", _ago(1), _ago(1), pr_number=71)],
        )
        job_count = 150
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(97000 + i, 9700, f"job-{i}", "success", labels='["depot-ubuntu-22.04-4"]')
                for i in range(job_count)
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=71, repo="PostHog/posthog")
        # Every job counts; before the LIMIT fix this capped at 100. 150 jobs x 120s = 300 min, depot
        # 4-core (2x) at $0.004/min = 300 x 0.004 x 2 = $2.40.
        assert cost.costed_jobs == job_count
        assert cost.estimated_cost_usd == pytest.approx(2.40)

    def test_pr_cost_clamps_clock_skewed_negative_durations(self) -> None:
        # Two jobs share one run/label group: a normal +120s job and a clock-skewed -120s one
        # (completed_at < started_at). The grouped sum must clamp the negative per-job (greatest(.,0))
        # so it doesn't cancel its group-mate's elapsed before the even-split expansion. Without the
        # clamp the group sums to 0s and the PR reads $0.00; with it, the skewed job contributes 0 and
        # the normal job's 120s survives = 2 billable min, depot 4-core (2x) at $0.004/min = $0.016.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(72, "alice", "open", 0, _ago(1), head_sha="sha72")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9800, "CI", "sha72", "completed", "success", _ago(1), _ago(1), pr_number=72)],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(98000, 9800, "ok", "success", started="2026-01-01 00:00:00", completed="2026-01-01 00:02:00"),
                _job_row(
                    98001, 9800, "skew", "success", started="2026-01-01 00:02:00", completed="2026-01-01 00:00:00"
                ),
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=72, repo="PostHog/posthog")
        assert cost.costed_jobs == 2
        assert cost.billable_minutes == pytest.approx(2.0)
        assert cost.estimated_cost_usd == pytest.approx(0.016)

    def test_pull_request_list_author_filter(self) -> None:
        # The author filter scopes the list to one author's PRs (drives the author page).
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                _pr_row(81, "alice", "open", 0, _ago(1), head_sha="sha81"),
                _pr_row(82, "bob", "open", 0, _ago(1), head_sha="sha82"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(8100, "CI", "sha81", "completed", "success", _ago(1), _ago(1), pr_number=81)],
        )
        assert {i.number for i in api.list_pull_requests(team=self.team, author="alice").items} == {81}
        assert {i.number for i in api.list_pull_requests(team=self.team, author="bob").items} == {82}

    def test_resolve_branch_orders_open_first(self) -> None:
        # The branch path matches the PR head ref (head.ref); open PRs come before merged/closed ones,
        # and PRs on other branches are excluded.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                _pr_row(62, "bob", "closed", 0, _ago(6), merged_at=_ago(1), head_sha="sha62", head_ref="feat/login"),
                _pr_row(61, "alice", "open", 0, _ago(2), head_sha="sha61", head_ref="feat/login"),
                _pr_row(63, "carol", "open", 0, _ago(1), head_sha="sha63", head_ref="other"),
            ],
        )
        # Source resolution requires the workflow_runs schema synced too (SPEC: both endpoints
        # required together), even though the branch path only reads the PR snapshot.
        self._create_table("github_workflow_runs", _WORKFLOW_RUNS_COLUMNS, [])
        matches = api.resolve_branch(team=self.team, branch="feat/login")
        assert [m.number for m in matches] == [61, 62]  # only feat/login PRs, open first
        # A branch matching no PR resolves to nothing (empty list, not an error).
        assert api.resolve_branch(team=self.team, branch="feat/nothing") == []

    def test_workflow_health_aggregates(self) -> None:
        self._seed()
        items = api.list_workflow_health(team=self.team, date_from="-30d")
        ci = next(item for item in items if item.workflow_name == "CI")
        assert ci.run_count == 2
        assert ci.success_rate == 0.5  # 1 success of 2 completed
        assert ci.last_failure_at is not None
        assert ci.billable_minutes is None  # no jobs source seeded → no cost figure

    def test_workflow_health_includes_cost_when_jobs_synced(self) -> None:
        # With the jobs source synced, each workflow carries its windowed billable cost + minutes.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(80, "alice", "open", 0, _ago(1), head_sha="sha80")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9500, "CI", "sha80", "completed", "success", _ago(1), _ago(1))],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [_job_row(95000, 9500, "build", "success", labels='["depot-ubuntu-22.04-4"]')],
        )
        ci = next(i for i in api.list_workflow_health(team=self.team, date_from="-30d") if i.workflow_name == "CI")
        assert ci.estimated_cost_usd is not None and ci.estimated_cost_usd > 0
        assert ci.billable_minutes is not None and ci.billable_minutes > 0

    def test_workflow_runner_costs_breaks_down_by_tier(self) -> None:
        # The single-workflow breakdown splits a workflow's spend across runner tiers.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(83, "alice", "open", 0, _ago(1), head_sha="sha83")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9600, "CI", "sha83", "completed", "success", _ago(1), _ago(1))],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(96000, 9600, "build", "success", labels='["depot-ubuntu-22.04-16"]'),
                _job_row(96001, 9600, "test", "success", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(96002, 9600, "e2e", "success", labels='["ubuntu-latest"]'),
            ],
        )
        costs = api.get_workflow_runner_costs(team=self.team, repo="PostHog/posthog", workflow_name="CI")
        by_label = {c.runner_label: c for c in costs}
        assert by_label["16-core"].provider == "self_hosted"
        assert by_label["16-core"].estimated_cost_usd is not None and by_label["16-core"].estimated_cost_usd > 0
        github_hosted = next(c for c in costs if c.provider == "github_hosted")
        assert github_hosted.estimated_cost_usd is None  # free tier: minutes/jobs only, no billable cost

    def test_workflow_health_daily_failures_exclude_non_failures(self) -> None:
        # The daily failure count is decisive failures only — skipped / cancelled / action_required
        # runs are completed but neither successes nor failures, so they must not inflate the trend.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(30, "alice", "open", 0, _ago(1), head_sha="sha30")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(6001, "CI", "sha-a", "completed", "success", _ago(1), _ago(1)),
                _run_row(6002, "CI", "sha-b", "completed", "failure", _ago(1), _ago(1)),
                _run_row(6003, "CI", "sha-c", "completed", "timed_out", _ago(1), _ago(1)),
                _run_row(6004, "CI", "sha-d", "completed", "skipped", _ago(1), _ago(1)),
                _run_row(6005, "CI", "sha-e", "completed", "cancelled", _ago(1), _ago(1)),
                _run_row(6006, "CI", "sha-f", "completed", "action_required", _ago(1), _ago(1)),
            ],
        )
        ci = next(i for i in api.list_workflow_health(team=self.team, date_from="-30d") if i.workflow_name == "CI")
        bucket = next(entry for entry in ci.buckets if entry.run_count > 0)
        # 6 completed, 1 success, 2 failures (failure + timed_out) — skipped/cancelled/action_required are neither.
        assert (bucket.completed, bucket.successes, bucket.failures) == (6, 1, 2)

    def test_workflow_health_last_failure_includes_timed_out(self) -> None:
        # last_failure_at must agree with the failure definition used by the trend: a workflow whose
        # only decisive failure is a timeout still has a "last failure".
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(31, "alice", "open", 0, _ago(1), head_sha="sha31")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(6101, "CI", "sha-g", "completed", "success", _ago(2), _ago(2)),
                _run_row(6102, "CI", "sha-h", "completed", "timed_out", _ago(1), _ago(1)),
            ],
        )
        ci = next(i for i in api.list_workflow_health(team=self.team, date_from="-30d") if i.workflow_name == "CI")
        assert ci.last_failure_at is not None
        # The latest completed run (the timeout) was decisive — drives the RED status badge.
        assert ci.latest_run_failed is True
        # And its raw conclusion is carried so the UI can distinguish a real pass from a non-failure.
        assert ci.latest_run_conclusion == "timed_out"

    def test_workflow_run_detail_by_id(self) -> None:
        # The run detail page fetches one run by id; re-runs share the id, so the latest attempt wins.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(42, "alice", "open", 0, _ago(1), head_sha="sha42")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    7777, "CI", "sha42", "completed", "failure", _ago(2), _ago(2), head_branch="master", pr_number=42
                ),
                _run_row(
                    7777,
                    "CI",
                    "sha42",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    head_branch="master",
                    pr_number=42,
                    run_attempt=2,
                ),
            ],
        )
        run = api.get_workflow_run(team=self.team, run_id=7777)
        assert run is not None
        assert run.id == 7777
        assert run.workflow_name == "CI"
        assert run.run_attempt == 2  # latest attempt wins
        assert run.conclusion == "success"
        assert run.status == "completed"
        assert run.head_branch == "master"
        assert run.pr_number == 42
        assert run.repo.owner == "PostHog" and run.repo.name == "posthog"
        assert run.duration_seconds is not None

        # An unknown id is None (the view turns this into a 404).
        assert api.get_workflow_run(team=self.team, run_id=99999) is None

    def test_workflow_run_list_scoped_to_workflow(self) -> None:
        # The workflow detail page lists one workflow's runs, newest first, scoped to its repo.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(50, "alice", "open", 0, _ago(1), head_sha="sha50")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(8001, "CI", "sha-a", "completed", "success", _ago(3), _ago(3)),
                _run_row(8002, "CI", "sha-b", "completed", "failure", _ago(1), _ago(1)),
                _run_row(8003, "Deploy", "sha-c", "completed", "success", _ago(2), _ago(2)),
                # Older than the default -30d window — excluded unless the caller widens the window.
                _run_row(8004, "CI", "sha-d", "completed", "success", _ago(60), _ago(60)),
            ],
        )
        ci_runs = api.list_workflow_runs(team=self.team, repo="PostHog/posthog", workflow_name="CI")
        assert [r.id for r in ci_runs] == [8002, 8001]  # only CI runs in the default window, newest first
        assert all(r.workflow_name == "CI" for r in ci_runs)

        # Widening the window pulls in the older run.
        wide = api.list_workflow_runs(team=self.team, repo="PostHog/posthog", workflow_name="CI", date_from="-90d")
        assert [r.id for r in wide] == [8002, 8001, 8004]

        # A repo with no such workflow yields an empty list (not an error).
        assert api.list_workflow_runs(team=self.team, repo="PostHog/posthog", workflow_name="Nope") == []

    def test_workflow_run_activity_projects_and_windows(self) -> None:
        # The chart endpoint returns compact per-run points over the window, newest first, with the
        # projection mapped in the right column order and an explicit (untruncated) cap signal.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(80, "alice", "open", 0, _ago(1), head_sha="sha80")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    8101, "CI", "sha-a", "completed", "failure", _ago(2), _ago(2), pr_number=80, head_branch="feat"
                ),
                _run_row(8102, "CI", "sha-b", "completed", "success", _ago(1), _ago(1)),
                _run_row(8103, "Deploy", "sha-c", "completed", "success", _ago(1), _ago(1)),
                # Older than the default -30d window — excluded unless the caller widens it.
                _run_row(8104, "CI", "sha-d", "completed", "success", _ago(60), _ago(60)),
            ],
        )
        activity = api.get_workflow_run_activity(team=self.team, repo="PostHog/posthog", workflow_name="CI")
        assert [p.run_id for p in activity.points] == [8102, 8101]  # only CI runs in window, newest first
        assert activity.truncated is False
        assert activity.limit == 2000
        # Each field maps to the right column — guards a wrong unpack order in _to_point.
        newest, failed = activity.points
        assert (newest.run_id, newest.conclusion, newest.pr_number) == (8102, "success", 0)
        assert (failed.conclusion, failed.head_branch, failed.pr_number) == ("failure", "feat", 80)
        # run_started_at is non-null on this endpoint — the window filter excludes unparseable-start runs.
        assert all(p.run_started_at is not None for p in activity.points)

        # Widening the window pulls in the older run.
        wide = api.get_workflow_run_activity(
            team=self.team, repo="PostHog/posthog", workflow_name="CI", date_from="-90d"
        )
        assert [p.run_id for p in wide.points] == [8102, 8101, 8104]

    def test_repo_run_activity_collapses_workflows_per_commit(self) -> None:
        # The repo-health chart folds every workflow run of a default-branch commit into ONE point: the
        # verdict is failure if any workflow failed, success if all settled and at least one passed, and
        # in-flight (null) while any is still running. Two workflows on the same head_sha must not yield
        # two dots. Runs off the default branch and outside the window are excluded.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(95, "alice", "open", 0, _ago(1), head_sha="sha95")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                # Commit A: two workflows, both passed -> one green dot with a wall-clock duration spanning
                # the earliest start to the latest finish (not either workflow's own duration).
                _run_row(9601, "CI", "sha-a", "completed", "success", _ago(3), _ago(2), head_branch="main"),
                _run_row(9602, "Deploy", "sha-a", "completed", "success", _ago(3), _ago(1), head_branch="main"),
                # Commit B: one workflow failed -> the whole commit is red even though the other passed.
                _run_row(9603, "CI", "sha-b", "completed", "failure", _ago(2), _ago(2), head_branch="main"),
                _run_row(9604, "Deploy", "sha-b", "completed", "success", _ago(2), _ago(2), head_branch="main"),
                # Commit C: one workflow still running -> in-flight, so conclusion and duration are null.
                _run_row(9605, "CI", "sha-c", "completed", "success", _ago(1), _ago(1), head_branch="main"),
                _run_row(9606, "Deploy", "sha-c", "in_progress", None, _ago(1), _ago(1), head_branch="main"),
                # A PR-branch commit and an out-of-window commit: both excluded from default-branch health.
                _run_row(9607, "CI", "sha-d", "completed", "failure", _ago(1), _ago(1), head_branch="feat"),
                _run_row(9608, "CI", "sha-e", "completed", "success", _ago(60), _ago(60), head_branch="main"),
            ],
        )
        activity = api.get_repo_run_activity(team=self.team)
        by_started = sorted(activity.points, key=lambda p: p.run_started_at)
        # Three default-branch commits in the window -> three points (six runs collapsed), oldest first here.
        assert len(activity.points) == 3
        commit_a, commit_b, commit_c = by_started
        assert commit_a.conclusion == "success"
        assert commit_a.duration_seconds is not None and commit_a.duration_seconds > 0
        assert commit_b.conclusion == "failure"
        # In-flight commit: unsettled workflow leaves the verdict and duration null (drops off the scatter).
        assert commit_c.conclusion is None
        assert commit_c.duration_seconds is None
        # Default-branch commits carry no single attributed PR.
        assert all(p.pr_number == 0 for p in activity.points)

    def test_workflow_detail_branch_filter(self) -> None:
        # The workflow detail page's runs list and runner-cost breakdown must honor the same branch scope
        # as the Workflows tab — without it, drilling in from a branch-scoped tab widened back to every
        # branch and showed more runs (and more cost) than the tab did.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(90, "alice", "open", 0, _ago(1), head_sha="sha90")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(8501, "CI", "sha-m1", "completed", "success", _ago(2), _ago(2), head_branch="main"),
                _run_row(8502, "CI", "sha-m2", "completed", "failure", _ago(1), _ago(1), head_branch="main"),
                _run_row(8503, "CI", "sha-r1", "completed", "success", _ago(1), _ago(1), head_branch="release"),
            ],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(85010, 8501, "build", "success", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(85020, 8502, "build", "success", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(85030, 8503, "build", "success", labels='["depot-ubuntu-22.04-4"]'),
            ],
        )
        repo, workflow = "PostHog/posthog", "CI"

        # Runs list: unfiltered spans every branch; scoped keeps only that branch's runs.
        all_runs = api.list_workflow_runs(team=self.team, repo=repo, workflow_name=workflow)
        assert {r.id for r in all_runs} == {8501, 8502, 8503}
        main_runs = api.list_workflow_runs(team=self.team, repo=repo, workflow_name=workflow, branch="main")
        assert {r.id for r in main_runs} == {8501, 8502}
        # A blank branch is "no filter", not a literal match on ''; an unknown branch yields nothing.
        assert len(api.list_workflow_runs(team=self.team, repo=repo, workflow_name=workflow, branch="  ")) == 3
        assert api.list_workflow_runs(team=self.team, repo=repo, workflow_name=workflow, branch="nope") == []

        # Runner costs: the branch scope narrows the costed jobs the same way (3 jobs → 2 on main).
        all_jobs = sum(
            c.job_count for c in api.get_workflow_runner_costs(team=self.team, repo=repo, workflow_name=workflow)
        )
        main_jobs = sum(
            c.job_count
            for c in api.get_workflow_runner_costs(team=self.team, repo=repo, workflow_name=workflow, branch="main")
        )
        assert (all_jobs, main_jobs) == (3, 2)

        # The activity chart honors the same branch scope as the runs list, so it can't plot other
        # branches' runs under an applied branch filter.
        all_activity = api.get_workflow_run_activity(team=self.team, repo=repo, workflow_name=workflow)
        assert {p.run_id for p in all_activity.points} == {8501, 8502, 8503}
        main_activity = api.get_workflow_run_activity(team=self.team, repo=repo, workflow_name=workflow, branch="main")
        assert {p.run_id for p in main_activity.points} == {8501, 8502}

    def test_pr_runs_span_all_commits(self) -> None:
        # The PR detail lists runs across all of the PR's commits (by association), not just head SHA.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(70, "alice", "open", 0, _ago(1), head_sha="shaA")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9300, "CI", "shaA", "completed", "success", _ago(2), _ago(2), pr_number=70),
                _run_row(9301, "CI", "shaB", "completed", "failure", _ago(1), _ago(1), pr_number=70),
                _run_row(9302, "CI", "shaC", "completed", "success", _ago(1), _ago(1), pr_number=71),
            ],
        )
        runs = api.list_pr_runs(team=self.team, pr_number=70, repo="PostHog/posthog")
        assert {r.id for r in runs} == {9300, 9301}  # only PR 70's runs
        assert {r.head_sha for r in runs} == {"shaA", "shaB"}  # across two commits

    def test_workflow_jobs_optional_and_costed(self) -> None:
        # Jobs are an optional source: absent → graceful empty; present → costed per runner tier.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(60, "alice", "open", 0, _ago(1), head_sha="sha60")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9100, "CI", "sha60", "completed", "failure", _ago(1), _ago(1))],
        )
        # No jobs table synced yet → empty, not an error (the graceful path).
        assert api.list_workflow_jobs(team=self.team, run_id=9100) == []

        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(91000, 9100, "build", "success", labels='["depot-ubuntu-22.04-16"]'),
                _job_row(91001, 9100, "e2e", "failure", labels='["ubuntu-latest"]'),
            ],
        )
        jobs = api.list_workflow_jobs(team=self.team, run_id=9100)
        assert {j.name for j in jobs} == {"build", "e2e"}
        build = next(j for j in jobs if j.name == "build")
        assert build.runner_provider == "self_hosted" and build.runner_label == "16-core"
        assert build.estimated_cost_usd is not None
        # github-hosted runner isn't billable → no cost estimate, and the provider reads as github_hosted.
        e2e = next(j for j in jobs if j.name == "e2e")
        assert e2e.runner_provider == "github_hosted" and e2e.estimated_cost_usd is None

    def test_workflow_run_detail_handles_null_timestamps(self) -> None:
        # A queued/barely-started run lands with empty timestamps; the mapper must yield None, not raise
        # a contract validation error (regression guard for nullable run_started_at/updated_at).
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(63, "alice", "open", 0, _ago(1), head_sha="sha63")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9300, "CI", "sha63", "queued", None, "", "", pr_number=63)],
        )
        run = api.get_workflow_run(team=self.team, run_id=9300)
        assert run is not None
        assert run.run_started_at is None and run.updated_at is None
        assert run.status == "queued" and run.conclusion is None
        # The list path maps the same sparse row without error.
        runs = api.list_pr_runs(team=self.team, pr_number=63, repo="PostHog/posthog")
        assert [r.id for r in runs] == [9300]

    def test_workflow_jobs_scoped_to_attempt(self) -> None:
        # A re-run carries multiple attempts under one run_id; the jobs query must not merge them.
        # Default (no run_attempt) returns the latest attempt; an explicit attempt returns just that one.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(62, "alice", "open", 0, _ago(1), head_sha="sha62")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(9200, "CI", "sha62", "completed", "success", _ago(1), _ago(1), run_attempt=2)],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(92000, 9200, "build", "failure", run_attempt=1),
                _job_row(92001, 9200, "test", "failure", run_attempt=1),
                _job_row(92002, 9200, "build", "success", run_attempt=2),
            ],
        )
        # Default: latest attempt (2) only — the failed first attempt's jobs don't leak in.
        latest = api.list_workflow_jobs(team=self.team, run_id=9200)
        assert {j.id for j in latest} == {92002}
        assert latest[0].conclusion == "success"
        # Explicit older attempt: just that attempt's jobs.
        first = api.list_workflow_jobs(team=self.team, run_id=9200, run_attempt=1)
        assert {j.id for j in first} == {92000, 92001}

    def test_pr_cost_aggregates_billable_jobs_across_runs(self) -> None:
        # PR cost sums the jobs of all the PR's runs (across commits), counting only billable Linux
        # runners; absent jobs source → graceful empty with jobs_available False.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(60, "alice", "open", 0, _ago(1), head_sha="sha60")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9100, "CI", "sha60a", "completed", "success", _ago(2), _ago(2), pr_number=60),
                _run_row(9101, "CI", "sha60b", "completed", "failure", _ago(1), _ago(1), pr_number=60),
                _run_row(9102, "CI", "sha99", "completed", "success", _ago(1), _ago(1), pr_number=61),
            ],
        )
        # No jobs table synced yet → every figure zero/None, cards hidden.
        empty = api.get_pr_cost(team=self.team, pr_number=60, repo="PostHog/posthog")
        assert empty.jobs_available is False and empty.estimated_cost_usd is None and empty.billable_minutes == 0.0

        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                # Two billable Linux jobs across two of the PR's runs, plus a github-hosted (excluded).
                _job_row(91000, 9100, "build", "success", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(91001, 9101, "test", "failure", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(91002, 9101, "e2e", "success", labels='["ubuntu-latest"]'),
                # A job on another PR's run must not leak into PR 60's cost.
                _job_row(91003, 9102, "build", "success", labels='["depot-ubuntu-22.04-16"]'),
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=60, repo="PostHog/posthog")
        assert cost.jobs_available is True
        assert cost.costed_jobs == 2  # the two depot Linux jobs on PR 60's runs
        assert cost.excluded_jobs == 1  # the github-hosted one
        assert cost.estimated_cost_usd is not None and cost.estimated_cost_usd > 0
        assert cost.billable_minutes == pytest.approx(4.0)  # 2 jobs x 2 min each (_job_row default window)
        # Per-workflow breakdown sums to the same: PR 60's runs are all the "CI" workflow.
        ci_cost = next(w for w in cost.by_workflow if w.workflow_name == "CI")
        assert ci_cost.costed_jobs == 2 and ci_cost.excluded_jobs == 1
        # Per-run breakdown keys by (run_id, run_attempt): each of the two runs carries one billable job
        # (run 9101's github-hosted e2e is excluded from its minutes), summing back to the PR total.
        by_run = {rc.run_id: rc for rc in cost.by_run}
        assert by_run[9100].billable_minutes == pytest.approx(2.0)
        assert by_run[9101].billable_minutes == pytest.approx(2.0)
        assert sum(rc.billable_minutes for rc in cost.by_run) == pytest.approx(cost.billable_minutes)

    def test_workflow_health_branch_filter(self) -> None:
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(20, "alice", "open", 0, _ago(1), head_sha="sha20")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(5001, "CI", "sha-m1", "completed", "success", _ago(2), _ago(2), head_branch="main"),
                _run_row(5002, "CI", "sha-m2", "completed", "failure", _ago(1), _ago(1), head_branch="main"),
                _run_row(5003, "CI", "sha-f1", "completed", "success", _ago(1), _ago(1), head_branch="feature/x"),
            ],
        )
        # Unfiltered: every branch's runs aggregate together.
        assert (
            next(
                i for i in api.list_workflow_health(team=self.team, date_from="-30d") if i.workflow_name == "CI"
            ).run_count
            == 3
        )

        # Scoped to a branch: only that branch's runs count, and rates recompute over them.
        main_only = next(
            i
            for i in api.list_workflow_health(team=self.team, date_from="-30d", branch="main")
            if i.workflow_name == "CI"
        )
        assert main_only.run_count == 2
        assert main_only.success_rate == 0.5

        # A blank branch is treated as "no filter", not a literal match on ''.
        assert (
            next(
                i
                for i in api.list_workflow_health(team=self.team, date_from="-30d", branch="  ")
                if i.workflow_name == "CI"
            ).run_count
            == 3
        )

        # A branch with no runs yields no rows.
        assert api.list_workflow_health(team=self.team, date_from="-30d", branch="nope") == []

    def test_pull_request_list_rollup_is_repo_qualified(self) -> None:
        # PR numbers restart per repo. Two repos share PR #10; the per-PR push / re-run rollup must
        # attribute each repo's runs to its own PR, not merge them on number alone. (The head-SHA CI
        # rollup is already repo-safe; this proves the runs_by_pr join is too.) A resolved source is
        # one repo today, so this is the defensive guarantee, exercised by seeding both into one.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                _pr_row(10, "alice", "open", 0, _ago(1), head_sha="sha10", full_name="PostHog/posthog"),
                _pr_row(10, "bob", "open", 0, _ago(1), head_sha="shaB10", full_name="PostHog/posthog.com"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(3001, "CI", "sha10", "completed", "success", _ago(1), _ago(1), pr_number=10),
                _run_row(
                    3002,
                    "CI",
                    "shaB10",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=10,
                    full_name="PostHog/posthog.com",
                ),
                # A second push + re-run on the other repo's PR #10 — must not leak onto posthog's #10.
                _run_row(
                    3003,
                    "CI",
                    "shaB10b",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=10,
                    run_attempt=2,
                    full_name="PostHog/posthog.com",
                ),
            ],
        )
        result = api.list_pull_requests(team=self.team)
        by_repo = {(item.repo.owner, item.repo.name): item for item in result.items}
        assert (by_repo[("PostHog", "posthog")].pushes, by_repo[("PostHog", "posthog")].rerun_cycles) == (1, 0)
        assert (by_repo[("PostHog", "posthog.com")].pushes, by_repo[("PostHog", "posthog.com")].rerun_cycles) == (2, 1)


class TestPRLLMSpendWarehouse(_WarehouseMixin, BaseTest):
    """LLM token spend attributed to a PR by git branch, over a real warehouse PR row plus
    $ai_generation events. Skips when object storage is unreachable."""

    def _generation(
        self,
        *,
        branch: str | None,
        days_ago: float,
        cost: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        repo: str | None = None,
        session: str | None = None,
        trace: str | None = None,
        event: str = "$ai_generation",
    ) -> None:
        # branch=None seeds an unstamped generation (no $ai_git_branch), the transient state the
        # carry-forward and prefix rules attribute; session/trace set the grouping key.
        props: dict[str, Any] = {
            "$ai_total_cost_usd": cost,
            "$ai_input_tokens": input_tokens,
            "$ai_output_tokens": output_tokens,
        }
        if branch is not None:
            props["$ai_git_branch"] = branch
        if repo is not None:
            props["$ai_git_repo"] = repo
        if session is not None:
            props["$ai_session_id"] = session
        if trace is not None:
            props["$ai_trace_id"] = trace
        _create_event(
            event=event,
            team=self.team,
            distinct_id="agent-1",
            properties=props,
            timestamp=timezone.now() - timedelta(days=days_ago),
        )

    def _seed_pr(self, number: int, head_ref: str, *, base_ref: str = "master") -> None:
        # A merged PR fixes the window to [created - 14d, merged] = [_ago(19), _ago(1)]. The runs table
        # must exist for the source to resolve even though LLM spend never reads it (mixin gotcha).
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    number,
                    "alice",
                    "closed",
                    0,
                    _ago(5),
                    merged_at=_ago(1),
                    head_sha=f"sha{number}",
                    head_ref=head_ref,
                    base_ref=base_ref,
                )
            ],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(number * 100, "CI", f"sha{number}", "completed", "success", _ago(4), _ago(4), pr_number=number)],
        )

    def test_llm_spend_attributes_by_branch_within_window(self) -> None:
        branch = "feat/tokens"
        self._seed_pr(80, branch)
        # Matches: on-branch, in-window; one with no repo stamped, one with the repo stamped equal.
        self._generation(branch=branch, days_ago=4, cost=1.0, input_tokens=100, output_tokens=50)
        self._generation(
            branch=branch, days_ago=10, cost=2.0, input_tokens=200, output_tokens=80, repo="PostHog/posthog"
        )
        # Excluded: wrong repo, wrong branch, before the lead window, after merge, wrong event type.
        self._generation(branch=branch, days_ago=4, cost=99.0, repo="other/repo")
        self._generation(branch="other-branch", days_ago=4, cost=99.0)
        self._generation(branch=branch, days_ago=25, cost=99.0)
        self._generation(branch=branch, days_ago=0, cost=99.0)
        self._generation(branch=branch, days_ago=4, cost=99.0, event="$ai_embedding")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=80, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 2
        assert cost.llm_spend.cost_usd == pytest.approx(3.0)
        assert cost.llm_spend.input_tokens == 300
        assert cost.llm_spend.output_tokens == 130

    def test_llm_spend_none_when_no_generations(self) -> None:
        # Open PR whose branch no event carries — spend stays null so the UI hides the row.
        self._create_table(
            "github_pull_requests",
            _PULL_REQUESTS_COLUMNS,
            [_pr_row(81, "alice", "open", 0, _ago(2), head_sha="sha81", head_ref="feat/empty")],
        )
        self._create_table(
            "github_workflow_runs",
            _WORKFLOW_RUNS_COLUMNS,
            [_run_row(8100, "CI", "sha81", "completed", "success", _ago(1), _ago(1), pr_number=81)],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=81, repo="PostHog/posthog")
        assert cost.llm_spend is None

    @parameterized.expand(
        [
            # first feature stamp == H: the base-stamped prefix and the H events all credit H.
            ("first_feature_is_head", "feat/tokens", 4, pytest.approx(14.0)),
            # first feature stamp == a different branch: the prefix belongs to that branch, so only
            # the later direct-H stamp credits H (guards against prefix-stealing).
            ("first_feature_is_other", "feat/other", 1, pytest.approx(8.0)),
        ]
    )
    def test_prefix_credits_head_only_when_first_feature_branch_is_head(
        self, _name: str, first_feature: str, expected_generations: int, expected_cost: Any
    ) -> None:
        head = "feat/tokens"
        self._seed_pr(82, head, base_ref="master")
        # Same session: base-stamped exploration, then the first feature stamp, then a direct H stamp.
        self._generation(branch="master", days_ago=10, cost=1.0, session="s1")
        self._generation(branch="master", days_ago=9, cost=1.0, session="s1")
        self._generation(branch=first_feature, days_ago=8, cost=4.0, session="s1")
        self._generation(branch=head, days_ago=6, cost=8.0, session="s1")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=82, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == expected_generations
        assert cost.llm_spend.cost_usd == expected_cost

    def test_carry_forward_follows_latest_stamp_until_a_branch_switch(self) -> None:
        self._seed_pr(83, "feat/tokens", base_ref="master")
        # H stamp, then an unstamped event that carries H forward, then a switch to another branch whose
        # later unstamped event must NOT credit H.
        self._generation(branch="feat/tokens", days_ago=10, cost=1.0, session="s2")
        self._generation(branch=None, days_ago=9, cost=2.0, session="s2")
        self._generation(branch="feat/other", days_ago=8, cost=99.0, session="s2")
        self._generation(branch=None, days_ago=7, cost=99.0, session="s2")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=83, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 2
        assert cost.llm_spend.cost_usd == pytest.approx(3.0)

    def test_out_of_window_events_excluded_even_in_an_eligible_session(self) -> None:
        self._seed_pr(84, "feat/tokens", base_ref="master")
        # In-window H stamp makes the session eligible; an unstamped event after the merge would carry H
        # forward if the window were dropped from the group scan, so it guards that outer-window filter.
        self._generation(branch="feat/tokens", days_ago=4, cost=1.0, session="s3")
        self._generation(branch=None, days_ago=0, cost=99.0, session="s3")
        self._generation(branch="feat/tokens", days_ago=25, cost=99.0, session="s3")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=84, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 1
        assert cost.llm_spend.cost_usd == pytest.approx(1.0)

    def test_ungrouped_events_count_only_via_a_direct_head_stamp(self) -> None:
        self._seed_pr(85, "feat/tokens", base_ref="master")
        # No session and no trace id: no group, so neither prefix nor carry-forward applies — only the
        # event stamped H directly counts.
        self._generation(branch="feat/tokens", days_ago=8, cost=5.0)
        self._generation(branch="master", days_ago=9, cost=99.0)
        self._generation(branch=None, days_ago=7, cost=99.0)
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=85, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 1
        assert cost.llm_spend.cost_usd == pytest.approx(5.0)

    def test_session_with_only_base_stamps_is_not_eligible(self) -> None:
        self._seed_pr(86, "feat/tokens", base_ref="master")
        # A session that never stamps the head ref is not eligible, so its base-stamped exploration
        # credits nothing and spend stays null.
        self._generation(branch="master", days_ago=10, cost=99.0, session="s4")
        self._generation(branch=None, days_ago=9, cost=99.0, session="s4")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=86, repo="PostHog/posthog")
        assert cost.llm_spend is None
