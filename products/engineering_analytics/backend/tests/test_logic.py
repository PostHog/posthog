import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from django.utils import timezone

import pandas as pd
from parameterized import parameterized

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import ExternalDataSourceType
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
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
    resolve_github_tables,
)
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
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

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
        assert [e.run_id for e in lifecycle.events] == [None, 2001, 2001, None]

    def test_returns_none_when_not_found(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([])):
            assert build_pr_lifecycle(team=self.team, pr_number=999, repo=None) is None

    @parameterized.expand(["PostHog", "PostHog/", "/posthog", "/"])
    def test_malformed_repo_raises_before_querying(self, repo: str) -> None:
        # A half-specified repo must fail loudly, not silently drop the filter and
        # return a PR from the wrong repo. Raises in _split_repo before any query.
        with self.assertRaises(ValueError):
            build_pr_lifecycle(team=self.team, pr_number=10, repo=repo)

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
    """Row mapping for the aggregate endpoints (the query method mocked, no warehouse).
    A GitHub source is connected (ORM only) so the resolver succeeds before the mocked
    query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

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
            result = build_pull_request_list(team=self.team, date_from="-30d")

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
        )
        with mock.patch(f"{_PR_LIST}._LIMIT", 2), mock.patch(_RUN_QUERY, return_value=_resp([row, row, row])):
            result = build_pull_request_list(team=self.team, date_from="-30d")

        assert result.truncated is True
        assert result.limit == 2
        assert len(result.items) == 2

    def test_workflow_health_maps_and_nulls_empty_window(self) -> None:
        rows = [
            ("PostHog", "posthog", "CI", 10, 0.9, 120.0, 600.0, _dt("2026-01-20T00:00:00")),
            # No completed runs: success_rate is NULL and quantileIf returns NaN — both map to None.
            ("PostHog", "posthog", "Deploy", 2, None, float("nan"), float("nan"), None),
        ]
        # Must be inside the -30d window, which is relative to now.
        daily_rows = [("PostHog", "posthog", "CI", datetime.now(tz=UTC).date() - timedelta(days=1), 10, 8, 7)]
        with mock.patch(_RUN_QUERY, side_effect=[_resp(rows), _resp(daily_rows)]):
            items = build_workflow_health(team=self.team, date_from="-30d", date_to=None)

        assert items[0].workflow_name == "CI" and items[0].success_rate == 0.9
        assert items[0].repo.owner == "PostHog" and items[0].repo.name == "posthog"
        # The daily series spans the whole window, zero-filled except the day with runs.
        assert len(items[0].daily) >= 30
        seeded_day = next(entry for entry in items[0].daily if entry.run_count > 0)
        assert (seeded_day.completed, seeded_day.successes) == (8, 7)
        assert all(entry.run_count == 0 for entry in items[1].daily)
        assert items[0].p50_seconds == 120.0 and items[0].p95_seconds == 600.0
        assert items[1].success_rate is None
        assert items[1].p50_seconds is None and items[1].p95_seconds is None
        assert items[1].last_failure_at is None


class TestResolveGitHubTables(BaseTest):
    """The per-team table resolver over the warehouse models (ORM only, no object storage).
    No source is connected in setUp so the missing-source path can be exercised."""

    def _connect(
        self,
        *,
        prefix: str,
        schemas: list[tuple[str, bool, bool]],
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
    ) -> ExternalDataSource:
        # schemas: (endpoint name, should_sync, has a backing table)
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
        )
        for name, should_sync, has_table in schemas:
            table = (
                create_warehouse_table_row(self.team, name=f"{prefix}github_{name}", source=source)
                if has_table
                else None
            )
            link_schema(self.team, source, name=name, table=table, should_sync=should_sync)
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
            build_ci_cards(team=self.team)

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
        assert [e.run_id for e in lifecycle.events] == [None, 2001, 2001, None]


class TestWorkflowHealthWindowCap(BaseTest):
    @parameterized.expand(["2000-01-01", "-500d"])
    def test_rejects_windows_beyond_a_year(self, date_from: str) -> None:
        with pytest.raises(ValueError, match="the maximum is 366"):
            build_workflow_health(team=self.team, date_from=date_from)


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
                _run_row(2001, "CI", "sha10", "completed", "failure", _ago(1), _ago(1)),
                _run_row(2002, "CI", "sha11", "completed", "success", _ago(2), _ago(2)),
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

    def test_workflow_health_aggregates(self) -> None:
        self._seed()
        items = api.list_workflow_health(team=self.team)
        ci = next(item for item in items if item.workflow_name == "CI")
        assert ci.run_count == 2
        assert ci.success_rate == 0.5  # 1 success of 2 completed
        assert ci.last_failure_at is not None
