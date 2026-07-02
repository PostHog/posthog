from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest, ClickhouseTestMixin

from products.uptime.backend.facade.enums import PingOutcome
from products.uptime.backend.logic import (
    DAILY_BUCKETS,
    delete_monitor,
    list_monitor_summaries,
    list_outages_for_monitor,
    record_ping,
    update_monitor,
)
from products.uptime.backend.models import Monitor
from products.uptime.backend.tests.conftest import UptimeTeamScopedTestMixin


class TestListMonitorSummaries(UptimeTeamScopedTestMixin, ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _ping(
        self,
        monitor: Monitor,
        *,
        outcome: PingOutcome,
        latency_ms: int = 100,
        status_code: int | None = 200,
        timestamp: datetime | None = None,
    ) -> None:
        record_ping(
            team_id=self.team.id,
            monitor_id=monitor.id,
            timestamp=timestamp or datetime.now(tz=ZoneInfo("UTC")),
            latency_ms=latency_ms,
            status_code=status_code,
            outcome=outcome,
        )

    def test_returns_no_data_for_monitor_without_pings(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="fresh", url="https://fresh.io")

        results = list_monitor_summaries(team_id=self.team.id)

        assert len(results) == 1
        row = results[0]
        assert row["id"] == monitor.id
        assert row["status"] == "no_data"
        assert row["uptime_90d"] is None
        assert row["last_ping_at"] is None
        assert row["last_ping_outcome"] is None
        assert row["avg_latency_24h_ms"] is None
        assert len(row["daily_buckets"]) == DAILY_BUCKETS
        assert all(b["status"] == "no_data" for b in row["daily_buckets"])

    def test_returns_up_for_monitor_with_only_successes(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="ok", url="https://ok.io")
        for _ in range(5):
            self._ping(monitor, outcome=PingOutcome.SUCCESS, latency_ms=120)

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["status"] == "up"
        assert row["uptime_90d"] == 1.0
        assert row["avg_latency_24h_ms"] == 120
        assert row["last_ping_outcome"] == PingOutcome.SUCCESS

    def test_derives_status_from_last_ping(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="flaky", url="https://flaky.io")
        now = datetime.now(tz=ZoneInfo("UTC"))
        self._ping(monitor, outcome=PingOutcome.SUCCESS, timestamp=now - timedelta(minutes=10))
        self._ping(monitor, outcome=PingOutcome.FAILURE, timestamp=now - timedelta(minutes=1))

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["status"] == "down"
        assert row["last_ping_outcome"] == PingOutcome.FAILURE

    def test_daily_buckets_classify_per_day(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="d", url="https://d.io")
        now = datetime.now(tz=ZoneInfo("UTC"))

        # Today: 4 success, 0 failure -> up
        for _ in range(4):
            self._ping(monitor, outcome=PingOutcome.SUCCESS, timestamp=now)
        # Yesterday: 3 success, 1 failure -> degraded
        for _ in range(3):
            self._ping(monitor, outcome=PingOutcome.SUCCESS, timestamp=now - timedelta(days=1))
        self._ping(monitor, outcome=PingOutcome.FAILURE, timestamp=now - timedelta(days=1))
        # 2 days ago: 2 failure, 0 success -> down
        for _ in range(2):
            self._ping(monitor, outcome=PingOutcome.FAILURE, timestamp=now - timedelta(days=2))

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        # daily_buckets is oldest-first; today is the last entry
        today_bucket = row["daily_buckets"][-1]
        yesterday_bucket = row["daily_buckets"][-2]
        two_days_ago_bucket = row["daily_buckets"][-3]
        assert today_bucket["status"] == "up"
        assert yesterday_bucket["status"] == "degraded"
        assert two_days_ago_bucket["status"] == "down"

    def test_uptime_90d_is_pings_minus_failures(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="u", url="https://u.io")
        for _ in range(9):
            self._ping(monitor, outcome=PingOutcome.SUCCESS)
        self._ping(monitor, outcome=PingOutcome.FAILURE)

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["uptime_90d"] == 0.9

    def test_handles_no_recent_successes_without_erroring(self) -> None:
        # ClickHouse's avgIf returns NaN when no rows match. Without NaN→None
        # normalization the int() conversion downstream raises ValueError and the
        # whole summary endpoint 500s, breaking the UI for fresh / down monitors.
        monitor = Monitor.objects.create(team_id=self.team.id, name="all-failures", url="https://nope.io")
        for _ in range(3):
            self._ping(monitor, outcome=PingOutcome.FAILURE, latency_ms=5000)

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["status"] == "down"
        assert row["avg_latency_24h_ms"] is None
        assert row["uptime_90d"] == 0.0

    def test_ignores_other_team_pings(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="mine", url="https://mine.io")
        self._ping(monitor, outcome=PingOutcome.SUCCESS)
        # Foreign ping under a different team_id should not affect our summary
        record_ping(
            team_id=self.team.id + 999,
            monitor_id=monitor.id,
            timestamp=datetime.now(tz=ZoneInfo("UTC")),
            latency_ms=999,
            status_code=500,
            outcome=PingOutcome.FAILURE,
        )

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["status"] == "up"
        assert row["uptime_90d"] == 1.0


class TestListOutages(UptimeTeamScopedTestMixin, ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_groups_failure_runs_into_outages(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="o", url="https://o.io")
        now = datetime.now(tz=ZoneInfo("UTC"))

        def ping(minutes_ago: int, outcome: PingOutcome, status_code: int | None = None) -> None:
            record_ping(
                team_id=self.team.id,
                monitor_id=monitor.id,
                timestamp=now - timedelta(minutes=minutes_ago),
                latency_ms=100,
                status_code=status_code,
                outcome=outcome,
            )

        # Resolved outage: two failures bounded by a success
        ping(60, PingOutcome.SUCCESS, 200)
        ping(50, PingOutcome.FAILURE, 503)
        ping(40, PingOutcome.FAILURE, 502)
        ping(30, PingOutcome.SUCCESS, 200)
        # Ongoing outage: trailing failure with no success after it
        ping(10, PingOutcome.FAILURE, 500)

        outages = list_outages_for_monitor(team_id=self.team.id, monitor_id=monitor.id)

        assert len(outages) == 2
        ongoing, resolved = outages[0], outages[1]
        assert ongoing["resolved_at"] is None
        assert ongoing["fail_count"] == 1
        assert ongoing["last_status_code"] == 500
        assert resolved["resolved_at"] is not None
        assert resolved["fail_count"] == 2
        assert resolved["last_status_code"] == 502


class TestUpdateMonitor(UptimeTeamScopedTestMixin, BaseTest):
    def test_updates_name_and_url(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="old", url="https://old.io")

        updated = update_monitor(team_id=self.team.id, monitor_id=monitor.id, name="new name", url="https://new.io")

        assert updated.name == "new name"
        assert updated.url == "https://new.io"
        monitor.refresh_from_db()
        assert monitor.name == "new name"
        assert monitor.url == "https://new.io"

    def test_updates_only_provided_fields(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="keep", url="https://keep.io")

        updated = update_monitor(team_id=self.team.id, monitor_id=monitor.id, url="https://changed.io")

        assert updated.name == "keep"  # untouched
        assert updated.url == "https://changed.io"


class TestDeleteMonitor(UptimeTeamScopedTestMixin, BaseTest):
    def test_removes_monitor(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="bye", url="https://bye.io")

        delete_monitor(team_id=self.team.id, monitor_id=monitor.id)

        assert not Monitor.objects.filter(team_id=self.team.id, id=monitor.id).exists()

    def test_delete_is_idempotent(self) -> None:
        # Deleting a non-existent monitor should not raise
        delete_monitor(team_id=self.team.id, monitor_id=uuid4())
