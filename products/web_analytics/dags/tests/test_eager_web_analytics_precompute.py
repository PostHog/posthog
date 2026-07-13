from collections.abc import MutableMapping
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone

import dagster
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.schema import WebAnalyticsPreComputeStrategy, WebStatsBreakdown

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Organization, Team

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.dags.eager_web_analytics_precompute import (
    BASELINE_BREAKDOWNS,
    BASELINE_WINDOW_DAYS,
    _resolve_eager_audience,
    _warm_baseline_for_team,
    warm_eager_baseline_op,
    web_analytics_eager_baseline_warming_job,
)

_EAGER_MODULE = "products.web_analytics.dags.eager_web_analytics_precompute"

# Total queries per team: WebOverview + WebGoals + WebVitalsPathBreakdown + each WebStats breakdown.
_QUERIES_PER_TEAM = 3 + len(BASELINE_BREAKDOWNS)


@contextmanager
def _eager_audience(team_ids):
    """Set the warmer audience (and, since the gate reads the same setting, the
    lazy-eligibility list) to `team_ids`."""
    with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=list(team_ids)):
        yield


def _make_preagg_job(
    team: Team,
    *,
    computed_at,
    status=PreaggregationJob.Status.READY,
    time_range_end=None,
) -> PreaggregationJob:
    end = time_range_end if time_range_end is not None else timezone.now()
    return PreaggregationJob.objects.create(
        team=team,
        time_range_start=end - timedelta(days=1),
        time_range_end=end,
        query_hash="a" * 64,
        status=status,
        computed_at=computed_at,
    )


@patch(f"{_EAGER_MODULE}.is_cloud", return_value=True)
class TestResolveEagerAudience:
    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[2, 7])
    def test_returns_team_ids_from_setting_on_cloud(self, _is_cloud):
        team_ids, reason, diag = _resolve_eager_audience()
        assert team_ids == [2, 7]
        assert reason == "ok"
        assert diag == {"teams_configured": 2}

    def test_returns_empty_on_self_hosted(self, _is_cloud):
        _is_cloud.return_value = False
        team_ids, reason, _diag = _resolve_eager_audience()
        assert team_ids == []
        assert reason == "not_cloud"

    @override_settings(
        WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[], WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[]
    )
    def test_returns_empty_when_no_teams_configured(self, _is_cloud):
        team_ids, reason, _diag = _resolve_eager_audience()
        assert team_ids == []
        assert reason == "no_teams_configured"

    @parameterized.expand(
        [
            ("unrestricted_only", [], [5], [5]),
            ("union_with_overlap", [2, 7], [7, 9], [2, 7, 9]),
            ("restricted_only", [2, 7], [], [2, 7]),
        ]
    )
    def test_audience_unions_restricted_and_unrestricted(self, _is_cloud, _name, restricted, unrestricted, expected):
        with override_settings(
            WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=restricted,
            WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=unrestricted,
        ):
            team_ids, reason, diag = _resolve_eager_audience()
        assert team_ids == expected
        assert reason == "ok"
        assert diag == {"teams_configured": len(expected)}


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestWarmEagerBaselineOp(APIBaseTest):
    """Integration-shaped tests for the op. Query runners are patched so
    no ClickHouse traffic is needed — we assert orchestration semantics."""

    def _enroll_teams(self, *, count: int) -> list[Team]:
        org = Organization.objects.create(name="Audience")
        return [Team.objects.create(organization=org, name=f"team-{i}") for i in range(count)]

    @patch(f"{_EAGER_MODULE}.WARM_TEAM_CONCURRENCY", 1)
    @patch(f"{_EAGER_MODULE}.tag_queries")
    @patch(f"{_EAGER_MODULE}.get_query_runner")
    def test_warms_least_recently_computed_teams_first(self, get_runner, _tag, _is_cloud):
        # Concurrency pinned to 1 so the pool drains `eligible` in order, making
        # the staleness ordering observable through the runner call sequence.
        never, old, recent = self._enroll_teams(count=3)
        now = timezone.now()
        _make_preagg_job(recent, computed_at=now)
        _make_preagg_job(old, computed_at=now - timedelta(days=2))
        # `never` has no PreaggregationJob row — it should warm first.
        get_runner.return_value = Mock(
            run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE))
        )

        # Enrol in reverse-staleness order to prove the sort (not the input) drives it.
        with _eager_audience([recent.pk, old.pk, never.pk]):
            warm_eager_baseline_op(dagster.build_op_context())

        seen: list[int] = []
        for call in get_runner.call_args_list:
            team = call.kwargs.get("team") or call.args[1]
            if not seen or seen[-1] != team.pk:
                seen.append(team.pk)
        assert seen == [never.pk, old.pk, recent.pk]

    @patch(f"{_EAGER_MODULE}.WARM_TEAM_CONCURRENCY", 1)
    @patch(f"{_EAGER_MODULE}.tag_queries")
    @patch(f"{_EAGER_MODULE}.get_query_runner")
    def test_staleness_ordering_ignores_out_of_window_and_non_ready_jobs(self, get_runner, _tag, _is_cloud):
        # `PreaggregationJob` is shared across products and has no product column, so the
        # ordering scopes its freshness signal to READY jobs covering the baseline window.
        # A recent-but-out-of-window job, or a recent non-READY job, must NOT make a team
        # look freshly warmed — both should still sort ahead of a genuinely warm team.
        genuine, noise_window, noise_status = self._enroll_teams(count=3)
        now = timezone.now()
        _make_preagg_job(genuine, computed_at=now)
        _make_preagg_job(noise_window, computed_at=now, time_range_end=now - timedelta(days=BASELINE_WINDOW_DAYS + 5))
        _make_preagg_job(noise_status, computed_at=now, status=PreaggregationJob.Status.STALE)
        get_runner.return_value = Mock(
            run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE))
        )

        with _eager_audience([genuine.pk, noise_window.pk, noise_status.pk]):
            warm_eager_baseline_op(dagster.build_op_context())

        seen: list[int] = []
        for call in get_runner.call_args_list:
            team = call.kwargs.get("team") or call.args[1]
            if not seen or seen[-1] != team.pk:
                seen.append(team.pk)
        # Both noise teams are treated as never-warmed (front); the genuinely warm team is last.
        assert seen[-1] == genuine.pk
        assert set(seen[:2]) == {noise_window.pk, noise_status.pk}

    @patch(f"{_EAGER_MODULE}.tag_queries")
    @patch(f"{_EAGER_MODULE}.get_query_runner")
    def test_team_logs_carry_processed_total_progress(self, get_runner, _tag, _is_cloud):
        get_runner.return_value = Mock(
            run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE))
        )
        teams = self._enroll_teams(count=3)
        with _eager_audience([t.pk for t in teams]), capture_logs() as cap_logs:
            warm_eager_baseline_op(dagster.build_op_context())
        team_logs = [log for log in cap_logs if log.get("event") == "eager_baseline_warming_team"]
        assert {log["processed"] for log in team_logs} == {1, 2, 3}
        assert all(log["total"] == 3 for log in team_logs)

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner, tag_queries_mock, _is_cloud):
        t1, t2 = self._enroll_teams(count=2)

        ok_runner = Mock()
        ok_runner.run.return_value = Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE)
        bad_runner = Mock()
        bad_runner.run.side_effect = RuntimeError("boom")

        def runner_factory(query, team, limit_context):
            return bad_runner if team.pk == t1.pk else ok_runner

        get_runner.side_effect = runner_factory

        with _eager_audience([t1.pk, t2.pk]):
            result = warm_eager_baseline_op(dagster.build_op_context())

        assert result["teams"] == 2
        assert result["warmed"] == _QUERIES_PER_TEAM  # only t2 succeeds
        assert result["failed"] == _QUERIES_PER_TEAM  # only t1 fails
        assert result["skipped"] == 0
        assert ok_runner.run.call_count == _QUERIES_PER_TEAM
        assert bad_runner.run.call_count == _QUERIES_PER_TEAM

        called_team_ids = {
            call.kwargs.get("team", call.args[1] if len(call.args) > 1 else None).pk
            for call in get_runner.call_args_list
        }
        assert called_team_ids == {t1.pk, t2.pk}

        # Tagging fires for every query so query_log attribution is intact.
        assert tag_queries_mock.call_count == _QUERIES_PER_TEAM * 2

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[])
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_returns_zeroed_metadata_when_no_teams_configured(self, get_runner, _is_cloud):
        result = warm_eager_baseline_op(dagster.build_op_context())
        assert result == {"teams": 0, "warmed": 0, "failed": 0, "skipped": 0}
        get_runner.assert_not_called()

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[99999999])
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_skips_team_ids_that_do_not_exist_in_db(self, get_runner, _is_cloud):
        # A team ID in the setting might be removed from the DB before the
        # setting is updated; the run should not crash.
        result = warm_eager_baseline_op(dagster.build_op_context())
        assert result == {"teams": 1, "warmed": 0, "failed": 0, "skipped": 1}
        get_runner.assert_not_called()


class TestWarmBaselineForTeam(APIBaseTest):
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_full_matrix(self, get_runner, tag_queries_mock):
        runner = Mock()
        runner.run.return_value = Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE)
        get_runner.return_value = runner

        warmed, failed = _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        assert warmed == _QUERIES_PER_TEAM
        assert failed == 0
        assert runner.run.call_count == _QUERIES_PER_TEAM
        # Force-refresh, not the default mode: the default respects the 6h result-cache
        # staleness and would skip warming while the precompute goes cold. Force-blocking
        # also keeps the warm inside run()'s rate-limit wrappers (vs a bare calculate()).
        for call in runner.run.call_args_list:
            assert call.kwargs["execution_mode"] == ExecutionMode.CALCULATE_BLOCKING_ALWAYS

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_flags_tiles_that_do_not_resolve_to_precompute(self, get_runner, tag_queries_mock):
        # A tile whose calculate() does not come back with preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE fell
        # through to raw — the warm populated no fresh precompute. It still counts as
        # "warmed" (it ran without error) but must be surfaced as not-precomputed.
        get_runner.return_value = Mock(
            run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LIVE))
        )

        with capture_logs() as cap_logs:
            warmed, failed = _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        assert warmed == _QUERIES_PER_TEAM
        assert failed == 0
        not_precomputed = [log for log in cap_logs if log.get("event") == "eager_baseline_warming_tile_not_precomputed"]
        assert len(not_precomputed) == _QUERIES_PER_TEAM

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_every_breakdown_with_correct_quirks(self, get_runner, tag_queries_mock):
        # PAGE/INITIAL_PAGE need includeBounceRate; vitals needs doPathCleaning.
        # Other breakdowns must NOT carry includeBounceRate.
        captured: list[dict] = []

        def capture(query, team, limit_context):
            captured.append(query)
            return Mock(run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE)))

        get_runner.side_effect = capture
        _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        kinds = {q["kind"] for q in captured}
        assert {"WebOverviewQuery", "WebGoalsQuery", "WebVitalsPathBreakdownQuery"}.issubset(kinds)

        windows = {q["dateRange"]["date_from"] for q in captured}
        assert windows == {f"-{BASELINE_WINDOW_DAYS}d"}

        # Every query must opt in to precompute and filter test accounts.
        assert all(q["useWebAnalyticsPrecompute"] is True for q in captured)
        assert all(q["filterTestAccounts"] is True for q in captured)

        vitals = next(q for q in captured if q["kind"] == "WebVitalsPathBreakdownQuery")
        assert vitals["doPathCleaning"] is True

        for q in captured:
            if q["kind"] != "WebStatsTableQuery":
                continue
            if q["breakdownBy"] in (WebStatsBreakdown.PAGE.value, WebStatsBreakdown.INITIAL_PAGE.value):
                assert q["includeBounceRate"] is True
            else:
                assert "includeBounceRate" not in q
            # Every path breakdown bakes cleaned-or-raw into the job hash, and the
            # dashboard sends doPathCleaning=true for teams with cleaning rules,
            # so the warmer must warm the variant those dashboards actually read.
            if q["breakdownBy"] in (
                WebStatsBreakdown.PAGE.value,
                WebStatsBreakdown.INITIAL_PAGE.value,
                WebStatsBreakdown.EXIT_PAGE.value,
            ):
                assert q["doPathCleaning"] is True
            else:
                assert "doPathCleaning" not in q

        # Every baseline breakdown must be covered.
        seen_breakdowns = {q["breakdownBy"] for q in captured if q["kind"] == "WebStatsTableQuery"}
        assert seen_breakdowns == {b.value for b in BASELINE_BREAKDOWNS}

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_tag_queries_fires_before_get_query_runner(self, get_runner, tag_queries_mock):
        # Order matters: tag_queries writes to a contextvar; any I/O the
        # runner does at construction time must inherit the warmer's tags.
        call_order: list[str] = []

        def record_tag(**kwargs):
            call_order.append("tag")

        def record_get_runner(**kwargs):
            call_order.append("get_runner")
            return Mock(run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE)))

        tag_queries_mock.side_effect = record_tag
        get_runner.side_effect = record_get_runner

        _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        # For each query in the matrix the order must be tag then get_runner.
        pairs = list(zip(call_order[0::2], call_order[1::2]))
        assert pairs and all(p == ("tag", "get_runner") for p in pairs)


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestEagerBaselineLogging(APIBaseTest):
    """The op mirrors lifecycle events to structlog so the run is queryable in
    Loki / PostHog — `context.log` alone only reaches the Dagster UI."""

    def _events(self, cap_logs: list[MutableMapping[str, Any]], name: str) -> list[MutableMapping[str, Any]]:
        return [log for log in cap_logs if log.get("event") == name]

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_emits_structured_lifecycle_events_on_success(self, get_runner, _tag, _is_cloud):
        get_runner.return_value = Mock(
            run=Mock(return_value=Mock(preComputeStrategy=WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE))
        )

        with _eager_audience([self.team.pk]), capture_logs() as cap_logs:
            warm_eager_baseline_op(dagster.build_op_context())

        start = self._events(cap_logs, "eager_baseline_warming_start")
        assert len(start) == 1
        assert start[0]["teams"] == 1
        assert start[0]["gate_reason"] == "ok"

        # Per-tile lifecycle: one start + one done line per tile, so the full
        # matrix is followable in the Dagster UI / Loki.
        tile_start = self._events(cap_logs, "eager_baseline_warming_tile_start")
        assert len(tile_start) == _QUERIES_PER_TEAM
        assert {t["tile"] for t in tile_start} == set(range(1, _QUERIES_PER_TEAM + 1))

        tile_done = self._events(cap_logs, "eager_baseline_warming_tile_done")
        assert len(tile_done) == _QUERIES_PER_TEAM
        # Verify the tile indices cover the full matrix (symmetric with tile_start)
        # so a wrong/constant idx in the done line can't slip through.
        assert {t["tile"] for t in tile_done} == set(range(1, _QUERIES_PER_TEAM + 1))
        assert all(t["status"] == "warmed" and "duration_ms" in t for t in tile_done)

        team_logs = self._events(cap_logs, "eager_baseline_warming_team")
        assert len(team_logs) == 1
        assert team_logs[0]["team_id"] == self.team.pk
        assert team_logs[0]["warmed"] == _QUERIES_PER_TEAM
        assert team_logs[0]["failed"] == 0
        assert "duration_ms" in team_logs[0]

        complete = self._events(cap_logs, "eager_baseline_warming_complete")
        assert len(complete) == 1
        assert complete[0]["warmed"] == _QUERIES_PER_TEAM
        assert complete[0]["failed"] == 0
        assert complete[0]["gate_reason"] == "ok"
        assert "duration_ms" in complete[0]

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_emits_query_failed_event_with_error_type(self, get_runner, _tag, _is_cloud):
        get_runner.return_value = Mock(run=Mock(side_effect=RuntimeError("boom")))

        with _eager_audience([self.team.pk]), capture_logs() as cap_logs:
            warm_eager_baseline_op(dagster.build_op_context())

        failed = self._events(cap_logs, "eager_baseline_warming_query_failed")
        assert len(failed) == _QUERIES_PER_TEAM
        assert all(f["error_type"] == "RuntimeError" for f in failed)
        assert all(f["team_id"] == self.team.pk for f in failed)
        assert all(f["status"] == "failed" and "duration_ms" in f for f in failed)

        # Every tile still emits a start even when its query fails.
        assert len(self._events(cap_logs, "eager_baseline_warming_tile_start")) == _QUERIES_PER_TEAM
        assert self._events(cap_logs, "eager_baseline_warming_tile_done") == []


@patch(f"{_EAGER_MODULE}.is_cloud", return_value=True)
class TestEagerLazyEligibilityGuards(APIBaseTest):
    """The warmer must never silently warm via the raw path: it skips
    lazy-ineligible teams and alarms when a warm run inserts no cache keys."""

    @patch(f"{_EAGER_MODULE}.tag_queries")
    @patch(f"{_EAGER_MODULE}.get_query_runner")
    def test_skips_team_that_is_not_lazy_eligible(self, get_runner, _tag, _is_cloud):
        # The team is in the audience but the gate reports it ineligible — a
        # drift the guard must catch rather than warm raw.
        with (
            override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.pk]),
            patch(f"{_EAGER_MODULE}.is_precompute_enabled_for_team", return_value=False),
            capture_logs() as cap_logs,
        ):
            result = warm_eager_baseline_op(dagster.build_op_context())

        assert result == {"teams": 1, "warmed": 0, "failed": 0, "skipped": 1}
        get_runner.assert_not_called()  # never warms a team it can't serve lazily
        events = [log for log in cap_logs if log.get("event") == "eager_baseline_warming_not_lazy_eligible"]
        assert len(events) == 1
        assert events[0]["team_id"] == self.team.pk


class TestJobConfiguration:
    def test_job_carries_dagster_max_runtime_tag(self):
        # Dagster terminates the run if it exceeds this; the next scheduled
        # tick (5 min later) starts fresh. Matches `web_preaggregated.py`.
        tags = web_analytics_eager_baseline_warming_job.tags
        assert tags is not None
        assert "dagster/max_runtime" in tags
        assert int(tags["dagster/max_runtime"]) >= 60
