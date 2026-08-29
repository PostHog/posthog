from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from temporalio.client import ScheduleOverlapPolicy

from posthog.schema import ChartDisplayType, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.temporal.schedule import schedules as temporal_schedules

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal import ACTIVITIES, WORKFLOWS
from products.signals.backend.temporal.report_metric_refresh.activities import (
    _whole_window_affected_users,
    collect_report_metric_refresh_page,
    collect_report_metric_refresh_page_activity,
    refresh_report_metric_snapshots_batch,
    refresh_report_metric_snapshots_batch_activity,
)
from products.signals.backend.temporal.report_metric_refresh.schedule import (
    SCHEDULE_ID,
    create_signals_report_metric_refresh_schedule,
)
from products.signals.backend.temporal.report_metric_refresh.types import (
    REPORT_METRIC_REFRESH_BATCH_SIZE,
    REPORT_METRIC_REFRESH_BATCH_TIMEOUT_SECONDS,
    REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES,
    REPORT_METRIC_REFRESH_MAX_REPORTS,
    REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS,
    REPORT_METRIC_REFRESH_SCHEDULE_MINUTES,
    ReportMetricRefreshBatchInput,
    ReportMetricRefreshPageInput,
    ReportMetricRefreshTarget,
)
from products.signals.backend.temporal.report_metric_refresh.workflow import (
    WORKFLOW_NAME,
    SignalReportMetricRefreshWorkflow,
)


def _metric(*, event: str = "$exception", value: float = 17) -> dict:
    return {
        "metric_id": "affected-users",
        "title": "Affected users",
        "kind": "affected_users",
        "role": "primary",
        "value": value,
        "value_at": "2026-08-29T12:00:00Z",
        "value_format": "count",
        "unit": "users",
        "query": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-30d"},
                "series": [{"kind": "EventsNode", "event": event, "math": "dau"}],
            },
        },
        "caption": None,
        "comparison": None,
    }


class TestReportMetricRefresh(APIBaseTest):
    def _report(self, **kwargs) -> SignalReport:
        defaults = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Impact report",
            "summary": "A current report",
            "metrics": [_metric()],
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def _batch_input(
        self,
        *reports: SignalReport,
        stale_before: datetime | None = None,
    ) -> ReportMetricRefreshBatchInput:
        return ReportMetricRefreshBatchInput(
            targets=[ReportMetricRefreshTarget(team_id=self.team.id, report_id=str(report.id)) for report in reports],
            stale_before=stale_before or timezone.now() + timedelta(minutes=1),
        )

    def test_discovery_keyset_pages_only_current_stale_reports(self) -> None:
        now = timezone.now()
        never_attempted = self._report()
        stale = self._report(
            status=SignalReport.Status.PENDING_INPUT,
            metrics_last_refresh_attempt_at=now - timedelta(hours=2),
        )
        self._report(metrics_last_refresh_attempt_at=now)
        self._report(status=SignalReport.Status.RESOLVED)
        self._report(metrics=[])

        first_page = collect_report_metric_refresh_page(
            ReportMetricRefreshPageInput(stale_before=now - timedelta(hours=1), page_size=1)
        )

        assert first_page.targets == [
            ReportMetricRefreshTarget(team_id=self.team.id, report_id=str(never_attempted.id))
        ]
        assert first_page.next_cursor is not None
        second_page = collect_report_metric_refresh_page(
            ReportMetricRefreshPageInput(
                stale_before=now - timedelta(hours=1),
                page_size=1,
                cursor=first_page.next_cursor,
            )
        )
        assert second_page.targets == [ReportMetricRefreshTarget(team_id=self.team.id, report_id=str(stale.id))]
        assert second_page.next_cursor is None

    def test_refresh_updates_snapshot_and_attempt_clock_without_reordering_report(self) -> None:
        good = self._report(metrics=[_metric(event="$good")])
        poison = self._report(metrics=[_metric(event="$poison")])
        malformed = self._report(metrics=[{"kind": "affected_users"}])
        original_updated_at = {report.id: report.updated_at for report in (good, poison, malformed)}
        cached_at = datetime(2026, 8, 29, 12, 30, tzinfo=UTC)

        def run_query(query: dict, _team) -> tuple[float, datetime]:
            if query["source"]["series"][0]["event"] == "$poison":
                raise ValueError("poison query")
            return 42.0, cached_at

        with patch(
            "products.signals.backend.temporal.report_metric_refresh.activities._whole_window_affected_users",
            side_effect=run_query,
        ):
            result = refresh_report_metric_snapshots_batch(self._batch_input(good, poison, malformed))

        assert result.attempted == 3
        assert result.updated == 1
        assert result.failed == 2
        for report in (good, poison, malformed):
            report.refresh_from_db()
            assert report.metrics_last_refresh_attempt_at is not None
            assert report.updated_at == original_updated_at[report.id]
        assert good.metrics[0]["value"] == 42.0
        assert good.metrics[0]["value_at"] == cached_at.isoformat()
        assert poison.metrics[0]["value"] == 17

    def test_activity_retry_skips_a_target_completed_after_the_sweep_cutoff(self) -> None:
        now = timezone.now()
        metric = _metric()
        metric["value_at"] = (now - timedelta(hours=2)).isoformat()
        report = self._report(metrics=[metric])
        inputs = self._batch_input(report, stale_before=now - timedelta(hours=1))

        with patch(
            "products.signals.backend.temporal.report_metric_refresh.activities._whole_window_affected_users",
            return_value=(42.0, now),
        ) as run_query:
            first_attempt = refresh_report_metric_snapshots_batch(inputs)
            retry = refresh_report_metric_snapshots_batch(inputs)

        assert first_attempt.updated == 1
        assert retry.attempted == 0
        assert retry.skipped == 1
        assert run_query.call_count == 1

    def test_snapshot_write_compares_and_swaps_the_complete_metric_state(self) -> None:
        report = self._report(metrics=[_metric(event="$old")])
        original_updated_at = report.updated_at

        def replace_metric_before_result(_query: dict, _team) -> tuple[float, datetime]:
            edited_metric = _metric(event="$old", value=99)
            edited_metric["caption"] = "Edited while the query was running."
            SignalReport.objects.filter(id=report.id).update(
                metrics=[edited_metric],
                metrics_last_refresh_attempt_at=None,
            )
            return 42.0, timezone.now()

        with patch(
            "products.signals.backend.temporal.report_metric_refresh.activities._whole_window_affected_users",
            side_effect=replace_metric_before_result,
        ):
            result = refresh_report_metric_snapshots_batch(self._batch_input(report))

        report.refresh_from_db()
        assert result.updated == 0
        assert result.skipped == 1
        assert report.metrics[0]["query"]["source"]["series"][0]["event"] == "$old"
        assert report.metrics[0]["caption"] == "Edited while the query was running."
        assert report.metrics[0]["value"] == 99
        assert report.metrics_last_refresh_attempt_at is None
        assert report.updated_at == original_updated_at

    def test_older_cached_measurement_does_not_overwrite_a_newer_snapshot(self) -> None:
        newer_measurement = timezone.now()
        metric = _metric()
        metric["value_at"] = newer_measurement.isoformat()
        report = self._report(metrics=[metric])
        original_updated_at = report.updated_at

        with patch(
            "products.signals.backend.temporal.report_metric_refresh.activities._whole_window_affected_users",
            return_value=(42.0, newer_measurement - timedelta(hours=1)),
        ):
            result = refresh_report_metric_snapshots_batch(self._batch_input(report))

        report.refresh_from_db()
        assert result.updated == 0
        assert result.skipped == 1
        assert report.metrics[0]["value"] == 17
        assert report.metrics[0]["value_at"] == newer_measurement.isoformat()
        assert report.metrics_last_refresh_attempt_at is not None
        assert report.updated_at == original_updated_at

    def test_attempt_clock_never_moves_backwards(self) -> None:
        now = timezone.now()
        newer_attempt = now + timedelta(minutes=5)
        metric = _metric()
        metric["value_at"] = (now - timedelta(hours=1)).isoformat()
        report = self._report(metrics=[metric], metrics_last_refresh_attempt_at=newer_attempt)
        inputs = self._batch_input(report, stale_before=newer_attempt + timedelta(minutes=1))

        with (
            patch(
                "products.signals.backend.temporal.report_metric_refresh.activities._whole_window_affected_users",
                return_value=(42.0, now),
            ),
            patch(
                "products.signals.backend.temporal.report_metric_refresh.activities.timezone.now",
                return_value=now,
            ),
        ):
            result = refresh_report_metric_snapshots_batch(inputs)

        report.refresh_from_db()
        assert result.updated == 1
        assert report.metrics_last_refresh_attempt_at == newer_attempt

    def test_correcting_a_malformed_metric_wins_the_attempt_marker_race(self) -> None:
        malformed = [{"kind": "affected_users"}]
        report = self._report(metrics=malformed)

        def correct_metric(_metrics: object):
            SignalReport.objects.filter(id=report.id).update(metrics=[_metric(event="$corrected")])
            return None

        with patch(
            "products.signals.backend.temporal.report_metric_refresh.activities._affected_users_metric",
            side_effect=correct_metric,
        ):
            result = refresh_report_metric_snapshots_batch(self._batch_input(report))

        report.refresh_from_db()
        assert result.failed == 1
        assert result.skipped == 1
        assert report.metrics_last_refresh_attempt_at is None

    def test_query_uses_cache_timestamp_and_offline_runner(self) -> None:
        cached_at = datetime(2026, 8, 29, 10, 15, tzinfo=UTC)
        stored_query = _metric()["query"]
        with patch.object(
            TrendsQueryRunner,
            "run",
            autospec=True,
            return_value=SimpleNamespace(results=[{"aggregated_value": 41}], last_refresh=cached_at),
        ) as run:
            value, measured_at = _whole_window_affected_users(stored_query, self.team)

        runner = run.call_args.args[0]
        assert runner.workload == Workload.OFFLINE
        assert runner.hogql_settings == HogQLGlobalSettings(
            max_execution_time=REPORT_METRIC_REFRESH_QUERY_TIMEOUT_SECONDS
        )
        assert runner.query.trendsFilter is not None
        assert runner.query.trendsFilter.display == ChartDisplayType.BOLD_NUMBER
        assert "trendsFilter" not in stored_query["source"]
        assert run.call_args.kwargs["execution_mode"] == ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        assert value == 41
        assert measured_at == cached_at

    def test_trends_runner_propagates_explicit_execution_settings(self) -> None:
        hogql_settings = HogQLGlobalSettings(max_execution_time=17)
        runner = TrendsQueryRunner(
            query=_metric()["query"]["source"],
            team=self.team,
            workload=Workload.OFFLINE,
            hogql_settings=hogql_settings,
        )
        response = HogQLQueryResponse(results=[], columns=[], timings=[])
        with (
            patch.object(runner, "to_queries", return_value=[ast.SelectQuery(select=[])]),
            patch.object(runner, "build_series_response", return_value=[]),
            patch(
                "posthog.hogql_queries.insights.trends.trends_query_runner.get_response_hogql",
                return_value=None,
            ),
            patch(
                "posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query",
                return_value=response,
            ) as execute,
        ):
            runner.calculate()

        assert execute.call_args.kwargs["workload"] == Workload.OFFLINE
        assert execute.call_args.kwargs["settings"] == hogql_settings


class TestReportMetricRefreshClickHouse(ClickhouseTestMixin, APIBaseTest):
    def test_whole_window_count_does_not_sum_daily_unique_users(self) -> None:
        _create_person(team_id=self.team.id, distinct_ids=["repeat-user"])
        _create_person(team_id=self.team.id, distinct_ids=["other-user"])
        _create_event(
            team=self.team,
            event="metric-refresh-event",
            distinct_id="repeat-user",
            timestamp=timezone.now() - timedelta(days=2),
        )
        _create_event(
            team=self.team,
            event="metric-refresh-event",
            distinct_id="repeat-user",
            timestamp=timezone.now() - timedelta(days=1),
        )
        _create_event(
            team=self.team,
            event="metric-refresh-event",
            distinct_id="other-user",
            timestamp=timezone.now() - timedelta(days=1),
        )
        flush_persons_and_events()

        value, _ = _whole_window_affected_users(_metric(event="metric-refresh-event")["query"], self.team)

        assert value == 2


class TestReportMetricRefreshSchedule(SimpleTestCase):
    def test_capacity_leaves_room_for_discovery_and_workflow_overhead(self) -> None:
        batch_count = (
            REPORT_METRIC_REFRESH_MAX_REPORTS + REPORT_METRIC_REFRESH_BATCH_SIZE - 1
        ) // REPORT_METRIC_REFRESH_BATCH_SIZE
        wave_count = (
            batch_count + REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES - 1
        ) // REPORT_METRIC_REFRESH_MAX_CONCURRENT_BATCHES

        assert REPORT_METRIC_REFRESH_MAX_REPORTS == 350
        assert wave_count == 7
        assert timedelta(seconds=wave_count * REPORT_METRIC_REFRESH_BATCH_TIMEOUT_SECONDS) + timedelta(
            minutes=5
        ) < timedelta(hours=1)

    async def test_schedule_is_registered_and_created_with_bounded_overlap(self) -> None:
        client = object()
        create = AsyncMock()
        with (
            patch(
                "products.signals.backend.temporal.report_metric_refresh.schedule.a_schedule_exists",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "products.signals.backend.temporal.report_metric_refresh.schedule.a_create_schedule",
                new=create,
            ),
        ):
            await create_signals_report_metric_refresh_schedule(client)  # type: ignore[arg-type]

        await_args = create.await_args
        assert await_args is not None
        _, schedule_id, schedule = await_args.args
        assert schedule_id == SCHEDULE_ID
        assert schedule.action.workflow == WORKFLOW_NAME
        assert schedule.action.execution_timeout == timedelta(hours=1)
        assert schedule.spec.intervals[0].every == timedelta(minutes=REPORT_METRIC_REFRESH_SCHEDULE_MINUTES)
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert SignalReportMetricRefreshWorkflow in WORKFLOWS
        assert collect_report_metric_refresh_page_activity in ACTIVITIES
        assert refresh_report_metric_snapshots_batch_activity in ACTIVITIES
        assert create_signals_report_metric_refresh_schedule in temporal_schedules
