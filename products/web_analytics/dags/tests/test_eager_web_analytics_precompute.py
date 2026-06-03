from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import dagster
from structlog.testing import capture_logs

from posthog.schema import WebStatsBreakdown

from posthog.models import Organization, Team

from products.web_analytics.dags.eager_web_analytics_precompute import (
    BASELINE_BREAKDOWNS,
    BASELINE_WINDOW_DAYS,
    EAGER_BASELINE_TEAM_IDS,
    _resolve_eager_audience,
    _warm_baseline_for_team,
    warm_eager_baseline_op,
    web_analytics_eager_baseline_warming_job,
)

# Total queries per team: WebOverview + WebGoals + WebVitalsPathBreakdown + each WebStats breakdown.
_QUERIES_PER_TEAM = 3 + len(BASELINE_BREAKDOWNS)


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestResolveEagerAudience:
    def test_returns_hardcoded_team_ids_on_cloud(self, _is_cloud):
        team_ids, reason, diag = _resolve_eager_audience()
        assert team_ids == list(EAGER_BASELINE_TEAM_IDS)
        assert reason == "ok"
        assert diag == {"teams_configured": len(EAGER_BASELINE_TEAM_IDS)}

    def test_returns_empty_on_self_hosted(self, _is_cloud):
        _is_cloud.return_value = False
        team_ids, reason, _diag = _resolve_eager_audience()
        assert team_ids == []
        assert reason == "not_cloud"

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS", ())
    def test_returns_empty_when_no_teams_configured(self, _is_cloud):
        team_ids, reason, _diag = _resolve_eager_audience()
        assert team_ids == []
        assert reason == "no_teams_configured"


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestWarmEagerBaselineOp(APIBaseTest):
    """Integration-shaped tests for the op. Query runners are patched so
    no ClickHouse traffic is needed — we assert orchestration semantics."""

    def _enroll_teams(self, *, count: int) -> list[Team]:
        org = Organization.objects.create(name="Audience")
        return [Team.objects.create(organization=org, name=f"team-{i}") for i in range(count)]

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner, tag_queries_mock, _is_cloud):
        t1, t2 = self._enroll_teams(count=2)

        ok_runner = Mock()
        ok_runner.run.return_value = None
        bad_runner = Mock()
        bad_runner.run.side_effect = RuntimeError("boom")

        def runner_factory(query, team, limit_context):
            return bad_runner if team.pk == t1.pk else ok_runner

        get_runner.side_effect = runner_factory

        with patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS",
            (t1.pk, t2.pk),
        ):
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

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS", ())
    def test_returns_zeroed_metadata_when_no_teams_configured(self, get_runner, _is_cloud):
        result = warm_eager_baseline_op(dagster.build_op_context())
        assert result == {"teams": 0, "warmed": 0, "failed": 0, "skipped": 0}
        get_runner.assert_not_called()

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_skips_team_ids_that_do_not_exist_in_db(self, get_runner, _is_cloud):
        # A team ID in the hardcoded list might be removed from the DB
        # before the constant is updated; the run should not crash.
        with patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS",
            (99999999,),
        ):
            result = warm_eager_baseline_op(dagster.build_op_context())
        assert result == {"teams": 1, "warmed": 0, "failed": 0, "skipped": 1}
        get_runner.assert_not_called()


class TestWarmBaselineForTeam(APIBaseTest):
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_full_matrix(self, get_runner, tag_queries_mock):
        runner = Mock()
        runner.run.return_value = None
        get_runner.return_value = runner

        warmed, failed = _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        assert warmed == _QUERIES_PER_TEAM
        assert failed == 0
        assert runner.run.call_count == _QUERIES_PER_TEAM

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_every_breakdown_with_correct_quirks(self, get_runner, tag_queries_mock):
        # PAGE/INITIAL_PAGE need includeBounceRate; vitals needs doPathCleaning.
        # Other breakdowns must NOT carry includeBounceRate.
        captured: list[dict] = []

        def capture(query, team, limit_context):
            captured.append(query)
            return Mock(run=Mock())

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
            return Mock(run=Mock())

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

    def _events(self, cap_logs: list[dict], name: str) -> list[dict]:
        return [log for log in cap_logs if log.get("event") == name]

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_emits_structured_lifecycle_events_on_success(self, get_runner, _tag, _is_cloud):
        org = Organization.objects.create(name="Audience")
        team = Team.objects.create(organization=org, name="t")
        get_runner.return_value = Mock(run=Mock(return_value=None))

        with (
            patch(
                "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS",
                (team.pk,),
            ),
            capture_logs() as cap_logs,
        ):
            warm_eager_baseline_op(dagster.build_op_context())

        start = self._events(cap_logs, "eager_baseline_warming_start")
        assert len(start) == 1
        assert start[0]["teams"] == 1
        assert start[0]["gate_reason"] == "ok"

        team_logs = self._events(cap_logs, "eager_baseline_warming_team")
        assert len(team_logs) == 1
        assert team_logs[0]["team_id"] == team.pk
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
        org = Organization.objects.create(name="Audience")
        team = Team.objects.create(organization=org, name="t")
        get_runner.return_value = Mock(run=Mock(side_effect=RuntimeError("boom")))

        with (
            patch(
                "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_BASELINE_TEAM_IDS",
                (team.pk,),
            ),
            capture_logs() as cap_logs,
        ):
            warm_eager_baseline_op(dagster.build_op_context())

        failed = self._events(cap_logs, "eager_baseline_warming_query_failed")
        assert len(failed) == _QUERIES_PER_TEAM
        assert all(f["error_type"] == "RuntimeError" for f in failed)
        assert all(f["team_id"] == team.pk for f in failed)


class TestJobConfiguration:
    def test_job_carries_dagster_max_runtime_tag(self):
        # Dagster terminates the run if it exceeds this; the next scheduled
        # tick (5 min later) starts fresh. Matches `web_preaggregated.py`.
        tags = web_analytics_eager_baseline_warming_job.tags
        assert tags is not None
        assert "dagster/max_runtime" in tags
        assert int(tags["dagster/max_runtime"]) >= 60
