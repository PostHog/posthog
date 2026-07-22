from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.logic import build_workflow_health
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_cost import query_cost_per_merge_series
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    _run_row,
    connect_github_source_without_data,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _RUN_QUERY,
    _ago,
    _ago_with_duration,
    _dt,
    _EndpointsWarehouseMixin,
    _job_row,
    _resp,
)


class TestWorkflowEndpointMapping(BaseTest):
    """Row mapping for the aggregate endpoints (the query method mocked, no warehouse).
    A GitHub source is connected (ORM only) so the resolver succeeds before the mocked
    query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_current_branch_health_counts_every_workflow(self) -> None:
        workflow_rows = [(f"Workflow {index}", 1, 0) for index in range(100)]
        workflow_rows.extend((f"Low-volume failure {index:02d}", 1, 1) for index in range(21))
        workflow_rows.append(("Still running", 0, 0))

        def run(sql: str, *, query_type: str, **kwargs) -> SimpleNamespace:
            if query_type == "engineering_analytics.default_branch":
                return _resp([(0, 12)])
            assert query_type == "engineering_analytics.current_branch_health"
            assert "LIMIT" not in sql.upper()
            return _resp(workflow_rows)

        with mock.patch(_RUN_QUERY, side_effect=run):
            health = api.get_current_branch_health(team=self.team)

        assert health.default_branch == "main"
        assert health.settled_workflows == 121
        assert health.failing_workflows == 21
        assert health.failing_workflow_names == [f"Low-volume failure {index:02d}" for index in range(20)]

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


class TestCostPerMergeSeries(BaseTest):
    """The cost-per-merged-PR trend on the repo hub: bucketing, zero-fill, and the cost/merge
    division guard. The two warehouse scans are mocked (curated fully faked), so this tests the
    Python fold — the bucket join, the trailing-window ratio, the empty-bucket handling — without a
    warehouse. Cost is aggregated in SQL over the shared cost source, so only the per-bucket dollar
    figure crosses the mock boundary."""

    @staticmethod
    def _curated(cost_rows: list[tuple], merges_rows: list[tuple], *, jobs_synced: bool = True) -> mock.Mock:
        curated = mock.Mock()
        curated.job_cost_source.return_value = "(cost_source)" if jobs_synced else None
        curated.pr_source.return_value = "px_github_pull_requests"
        # Cost scan first, then the merges scan — the call order in query_cost_per_merge_series.
        curated.run.side_effect = [_resp(cost_rows), _resp(merges_rows)]
        return curated

    def test_buckets_cost_per_merge_and_zero_fills(self) -> None:
        date_from = _dt("2026-06-01T00:00:00")
        date_to = _dt("2026-06-30T00:00:00")  # 29-day window -> day granularity, deterministic buckets.
        # Columns: bucket_start, billable_seconds, cost_sum, costed, unsettled, excluded — the SQL cost
        # aggregates. depot-4 (4-core) bills at 2x, so 2 min -> 2 * 0.004 * 2 = 0.016; 1 min -> 0.008.
        cost_rows = [
            (datetime(2026, 6, 2), 120.0, 0.016, 1, 0, 0),
            (datetime(2026, 6, 3), 60.0, 0.008, 1, 0, 0),
            (datetime(2026, 6, 6), 120.0, 0.016, 1, 0, 0),  # cost but no merges below
        ]
        # Columns: bucket_start, merges.
        merges_rows = [
            (datetime(2026, 6, 2), 4),
            (datetime(2026, 6, 3), 2),
            (datetime(2026, 6, 5), 3),  # merges but no cost above
        ]
        buckets = query_cost_per_merge_series(
            curated=self._curated(cost_rows, merges_rows), date_from=date_from, date_to=date_to, granularity="day"
        )

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
        buckets = query_cost_per_merge_series(
            curated=curated, date_from=_dt("2026-06-01T00:00:00"), date_to=_dt("2026-06-30T00:00:00"), granularity="day"
        )
        assert buckets == []
        curated.run.assert_not_called()  # no jobs source -> no scan is issued


class TestWorkflowHealthWindowCap(BaseTest):
    @parameterized.expand(["2000-01-01", "-500d"])
    def test_rejects_windows_beyond_a_year(self, date_from: str) -> None:
        # The window cap is build_workflow_health's own guard, reached before it reads any data; a
        # handle with dummy table names exposes the team (for timezone) and nothing else is touched.
        curated = CuratedGitHubSource(team=self.team, tables=GitHubTables(pull_requests="pr", workflow_runs="wr"))
        with pytest.raises(ValueError, match="the maximum is 366"):
            build_workflow_health(curated=curated, date_from=date_from)


class TestWorkflowEndpointsWarehouse(_EndpointsWarehouseMixin, BaseTest):
    """Workflow-scoped end-to-end aggregates over the shared seeded warehouse tables."""

    def test_repo_overview_headlines_and_series_toggle(self) -> None:
        # The weekly digest's whole read path: headline aggregates with include_series=False must
        # still carry every number the digest renders — merged counts over ALL merged PRs (bots
        # included: the merge population that triggered the spend) while the median keeps the
        # locked bots/drafts-excluded recipe, plus job-backed billable minutes — with all four
        # chart series empty. The default call keeps the series for the UI.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                # human, merged in window: open->merge = 8 days; the median's only sample
                _pr_row(80, "alice", "closed", 0, _ago(10), merged_at=_ago(2), head_sha="sha80"),
                # bot, merged in window: counted in merged_pr_count, excluded from the median
                _pr_row(81, "dependabot[bot]", "closed", 0, _ago(4), merged_at=_ago(3), head_sha="sha81"),
                # merged before the window (and before its prev twin): in neither count
                _pr_row(82, "alice", "closed", 0, _ago(120), merged_at=_ago(90), head_sha="sha82"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9500, "CI", "sha80", "completed", "success", _ago(2), _ago(2), pr_number=80),
                _run_row(9501, "CI", "sha81", "completed", "success", _ago(3), _ago(3), pr_number=81, run_attempt=2),
            ],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [_job_row(95000, 9500, "build", "success", labels='["depot-ubuntu-22.04-4"]')],
        )

        overview = api.get_repo_overview(team=self.team, include_series=False)
        assert overview.merged_pr_count == 2  # 80 and 81; 82 merged long before the window
        assert overview.merged_pr_count_prev == 0
        assert overview.median_open_to_merge_seconds == pytest.approx(8 * 86400)  # bot PR 81 excluded
        assert overview.run_count == 2
        assert overview.rerun_cycles == 1
        assert overview.billable_minutes == pytest.approx(2.0)  # one 120s job on a billable tier
        assert overview.estimated_cost_usd == pytest.approx(0.016)  # 2 min x $0.004 x 2 (4-core)
        assert overview.cost_series == []
        assert overview.time_to_green_series == []
        assert overview.success_rate_series == []
        assert overview.open_to_merge_series == []
        assert overview.cost_series_granularity == "day"  # the grain the series would have used

        with_series = api.get_repo_overview(team=self.team)
        assert len(with_series.cost_series) > 0  # zero-filled spine across the default -30d window
        assert len(with_series.success_rate_series) > 0

    def test_workflow_health_aggregates(self) -> None:
        self._seed()
        items = api.list_workflow_health(team=self.team, date_from="-30d")
        ci = next(item for item in items if item.workflow_name == "CI")
        assert ci.run_count == 2
        assert ci.success_rate == 0.5  # 1 success of 2 completed
        assert ci.last_failure_at is not None
        assert ci.billable_minutes is None  # no jobs source seeded → no cost figure

    def test_workflow_health_prev_window_survives_raw_scan_floor(self) -> None:
        # The prev-window query's raw-string scan floor must come from prev_from, not date_from.
        # A run in [prev_from, date_from) sits below the date_from floor; if that floor leaked into
        # the prev scan the innermost raw prefilter would drop it and success_rate_prev would go None.
        # A -30d window puts its prev twin at [-60d, -30d), so _ago(45) lands squarely in it.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(60, "alice", "open", 0, _ago(2), head_sha="sha60")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(6001, "CI", "sha60", "completed", "success", _ago(2), _ago(2), pr_number=60),
                _run_row(6002, "CI", "sha60p", "completed", "success", _ago(45), _ago(45), pr_number=60),
            ],
        )
        ci = next(i for i in api.list_workflow_health(team=self.team, date_from="-30d") if i.workflow_name == "CI")
        assert ci.success_rate == 1.0
        assert ci.success_rate_prev == 1.0

    def test_workflow_health_duration_percentiles_exclude_cancelled_failed_and_noop_runs(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(90, "alice", "open", 0, _ago(1), head_sha="sha90")],
        )
        # Every real success shares one duration, so the percentile population is exactly 100; any
        # leaked cancel (1s), failure (1000s), or no-op gate success (4s) moves p50/p95 off 100.
        conclusions = [("success", 100)] * 2 + [("success", 4)] * 3 + [("cancelled", 1)] * 3 + [("failure", 1000)]
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    9000 + index,
                    "CI",
                    f"{conclusion}-{index}",
                    "completed",
                    conclusion,
                    *_ago_with_duration(1, duration_seconds),
                    pr_number=90,
                    head_branch="feature/ci",
                )
                for index, (conclusion, duration_seconds) in enumerate(conclusions)
            ]
            # An all-fast workflow has no real successes — its percentiles fall back to every
            # successful run instead of reading as missing.
            + [
                _run_row(9100, "Guard", "guard-1", "completed", "success", *_ago_with_duration(1, 4)),
                _run_row(9101, "Guard", "guard-2", "completed", "success", *_ago_with_duration(2, 4)),
            ],
        )

        health = api.list_workflow_health(team=self.team, date_from="-30d")
        ci = next(item for item in health if item.workflow_name == "CI")

        # Counts and rate stay over all/completed runs; only the duration population narrows.
        assert ci.run_count == 9
        assert ci.success_rate == pytest.approx(5 / 9)
        assert ci.p50_seconds == pytest.approx(100)
        assert ci.p95_seconds == pytest.approx(100)

        guard = next(item for item in health if item.workflow_name == "Guard")
        assert guard.p50_seconds == pytest.approx(4)

    def test_workflow_health_pull_request_scope_excludes_default_branch_and_unattributed_runs(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(91, "alice", "open", 0, _ago(1), head_sha="sha91")],
        )
        # The scenario matrix: PR-attributed × head branch. Only the attributed feature-branch
        # run belongs in the pull_request scope.
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(run_id, "CI", sha, "completed", "success", _ago(1), _ago(1), pr_number=pr, head_branch=head)
                for run_id, sha, pr, head in [
                    (9101, "sha-pr", 91, "feature/pr"),
                    (9102, "sha-master", None, "master"),
                    (9103, "sha-master-pr", 91, "master"),
                    (9104, "sha-branch", None, "feature/no-pr"),
                    (9105, "sha-main-pr", 91, "main"),
                ]
            ],
        )

        pull_request = next(
            item
            for item in api.list_workflow_health(team=self.team, date_from="-30d", run_scope="pull_request")
            if item.workflow_name == "CI"
        )

        # 1 exactly: over-exclusion drops to 0, a leaked master/main/unattributed row raises it above 1.
        assert pull_request.run_count == 1

    def test_workflow_health_includes_cost_when_jobs_synced(self) -> None:
        # With the jobs source synced, each workflow carries its windowed billable cost + minutes.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(80, "alice", "open", 0, _ago(1), head_sha="sha80")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(83, "alice", "open", 0, _ago(1), head_sha="sha83")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(30, "alice", "open", 0, _ago(1), head_sha="sha30")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(31, "alice", "open", 0, _ago(1), head_sha="sha31")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(42, "alice", "open", 0, _ago(1), head_sha="sha42")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(50, "alice", "open", 0, _ago(1), head_sha="sha50")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
        # No-op gate runs (benign conclusion, settled in seconds) are hidden by the endpoint — real
        # runs fill the cap first — while fast failures and in-flight runs stay, and an all-fast
        # workflow falls back to showing everything.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(80, "alice", "open", 0, _ago(1), head_sha="sha80")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                # A fast failure is signal (broken config fails in seconds) — never filtered as no-op.
                _run_row(
                    8101,
                    "CI",
                    "sha-a",
                    "completed",
                    "failure",
                    *_ago_with_duration(2, 4),
                    pr_number=80,
                    head_branch="feat",
                ),
                _run_row(8102, "CI", "sha-b", "completed", "success", *_ago_with_duration(1, 300)),
                _run_row(8103, "Deploy", "sha-c", "completed", "success", *_ago_with_duration(1, 300)),
                # Older than the default -30d window — excluded unless the caller widens it.
                _run_row(8104, "CI", "sha-d", "completed", "success", *_ago_with_duration(60, 120)),
                # A no-op gate run: succeeded in seconds without doing real work — off the chart.
                _run_row(8105, "CI", "sha-e", "completed", "success", *_ago_with_duration(1, 4)),
                # Still running: no duration yet, but it must stay (it feeds the in-flight band).
                _run_row(8106, "CI", "sha-f", "in_progress", None, _ago(3), _ago(3)),
                # Completed fast but with a NULL conclusion (conclusions can lag the sync) — undecided,
                # so it must stay; a non-NULL-safe no-op flag would silently drop it.
                _run_row(8107, "CI", "sha-g", "completed", None, *_ago_with_duration(4, 4)),
                # A legitimately fast workflow: every run finishes in seconds. Duration alone can't
                # tell it from a gate no-op, so with no real runs to show the filter must stand down.
                _run_row(8110, "Guard", "sha-h", "completed", "success", *_ago_with_duration(2, 3)),
                _run_row(8111, "Guard", "sha-i", "completed", "success", *_ago_with_duration(1, 4)),
                # A sparse workflow: one real execution, one in flight, one fast no-op. The in-flight
                # run has no duration to plot, so dropping the no-op would leave the scatter below its
                # 2-point minimum — the fallback must count duration-bearing runs, not kept rows.
                _run_row(8120, "Sparse", "sha-j", "completed", "success", *_ago_with_duration(3, 300)),
                _run_row(8121, "Sparse", "sha-k", "in_progress", None, _ago(2), _ago(2)),
                _run_row(8122, "Sparse", "sha-l", "completed", "success", *_ago_with_duration(1, 4)),
            ],
        )
        activity = api.get_workflow_run_activity(team=self.team, repo="PostHog/posthog", workflow_name="CI")
        # Only CI runs in window, newest first; the no-op 8105 is excluded, the in-flight 8106 and the
        # fast-but-undecided 8107 are kept.
        assert [p.run_id for p in activity.points] == [8102, 8101, 8106, 8107]
        assert activity.truncated is False
        assert activity.limit == 2000
        # Each field maps to the right column — guards a wrong unpack order in _to_point.
        newest, failed, in_flight, undecided = activity.points
        assert (newest.run_id, newest.conclusion, newest.pr_number) == (8102, "success", 0)
        assert (failed.conclusion, failed.head_branch, failed.pr_number) == ("failure", "feat", 80)
        assert (in_flight.conclusion, in_flight.duration_seconds) == (None, None)
        assert (undecided.conclusion, undecided.duration_seconds) == (None, 4)
        # run_started_at is non-null on this endpoint — the window filter excludes unparseable-start runs.
        assert all(p.run_started_at is not None for p in activity.points)

        # Widening the window pulls in the older run.
        wide = api.get_workflow_run_activity(
            team=self.team, repo="PostHog/posthog", workflow_name="CI", date_from="-90d"
        )
        assert [p.run_id for p in wide.points] == [8102, 8101, 8106, 8107, 8104]

        # An all-fast workflow keeps its history: with no real runs left to show, hiding the no-ops
        # would blank the chart, so the filter stands down and both runs come back.
        guard = api.get_workflow_run_activity(team=self.team, repo="PostHog/posthog", workflow_name="Guard")
        assert [p.run_id for p in guard.points] == [8111, 8110]

        # One plottable real run isn't enough for the scatter either — the no-op stays visible too.
        sparse = api.get_workflow_run_activity(team=self.team, repo="PostHog/posthog", workflow_name="Sparse")
        assert [p.run_id for p in sparse.points] == [8122, 8121, 8120]

    def test_repo_run_activity_collapses_workflows_per_commit(self) -> None:
        # The repo-health chart folds every workflow run of a default-branch commit into ONE point: the
        # verdict is failure if any workflow failed, success if all settled and at least one passed, and
        # in-flight (null) while any is still running. Two workflows on the same head_sha must not yield
        # two dots. Runs off the default branch and outside the window are excluded.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(95, "alice", "open", 0, _ago(1), head_sha="sha95")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(90, "alice", "open", 0, _ago(1), head_sha="sha90")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(8501, "CI", "sha-m1", "completed", "success", *_ago_with_duration(2, 60), head_branch="main"),
                _run_row(8502, "CI", "sha-m2", "completed", "failure", *_ago_with_duration(1, 60), head_branch="main"),
                _run_row(
                    8503, "CI", "sha-r1", "completed", "success", *_ago_with_duration(1, 60), head_branch="release"
                ),
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

    def test_workflow_jobs_optional_and_costed(self) -> None:
        # Jobs are an optional source: absent → graceful empty; present → costed per runner tier.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(60, "alice", "open", 0, _ago(1), head_sha="sha60")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(63, "alice", "open", 0, _ago(1), head_sha="sha63")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
            PULL_REQUESTS_COLUMNS,
            [_pr_row(62, "alice", "open", 0, _ago(1), head_sha="sha62")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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

    def test_workflow_health_branch_filter(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(20, "alice", "open", 0, _ago(1), head_sha="sha20")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
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
