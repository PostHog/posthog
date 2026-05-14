from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.utils import timezone

from products.uptime.backend import logic
from products.uptime.backend.facade.enums import PingOutcome
from products.uptime.backend.logic import (
    DAILY_BUCKETS,
    bulk_create_monitors,
    delete_monitor,
    list_monitor_summaries,
    list_suggested_urls,
    record_ping,
    reorder_monitors,
    update_monitor,
)
from products.uptime.backend.models import Monitor
from products.uptime.backend.tests.conftest import UptimeTeamScopedTestMixin

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))


def _pageview(team, distinct_id: str, host: str, path: str = "/", timestamp: datetime | None = None) -> None:
    _create_event(
        team=team,
        distinct_id=distinct_id,
        event="$pageview",
        timestamp=timestamp or NOW,
        properties={"$current_url": f"https://{host}{path}", "$host": host, "$pathname": path},
    )


class TestListSuggestedUrls(UptimeTeamScopedTestMixin, ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _create_person(distinct_ids=["u1"], team=self.team)
        _create_person(distinct_ids=["u2"], team=self.team)

    def test_ranks_hosts_by_event_count(self) -> None:
        with freeze_time(NOW):
            for _ in range(5):
                _pageview(self.team, "u1", "posthog.com")
            for _ in range(3):
                _pageview(self.team, "u1", "github.com")
            _pageview(self.team, "u2", "stripe.com")

            results = list_suggested_urls(team_id=self.team.id, days=30, limit=10)

        assert [r["host"] for r in results] == ["posthog.com", "github.com", "stripe.com"]
        assert [r["event_count"] for r in results] == [5, 3, 1]
        assert all(r["url"].startswith("https://") for r in results)

    def test_counts_unique_paths_per_host(self) -> None:
        with freeze_time(NOW):
            _pageview(self.team, "u1", "posthog.com", "/")
            _pageview(self.team, "u1", "posthog.com", "/pricing")
            _pageview(self.team, "u1", "posthog.com", "/pricing")  # duplicate path
            _pageview(self.team, "u1", "posthog.com", "/docs")

            results = list_suggested_urls(team_id=self.team.id, days=30, limit=10)

        assert len(results) == 1
        assert results[0]["host"] == "posthog.com"
        assert results[0]["event_count"] == 4
        assert results[0]["unique_paths"] == 3

    def test_excludes_unpingable_hosts(self) -> None:
        with freeze_time(NOW):
            _pageview(self.team, "u1", "posthog.com")
            _pageview(self.team, "u1", "localhost")
            _pageview(self.team, "u1", "localhost:3000")
            _pageview(self.team, "u1", "my-app.local")
            _pageview(self.team, "u1", "10.0.0.1")
            _pageview(self.team, "u1", "192.168.1.1:8080")
            _pageview(self.team, "u1", "no-dot-host")

            results = list_suggested_urls(team_id=self.team.id, days=30, limit=10)

        assert [r["host"] for r in results] == ["posthog.com"]

    def test_excludes_already_monitored_hosts(self) -> None:
        Monitor.objects.create(team_id=self.team.id, name="github", url="https://github.com")
        Monitor.objects.create(team_id=self.team.id, name="ph", url="https://posthog.com/with/path")

        with freeze_time(NOW):
            _pageview(self.team, "u1", "posthog.com")
            _pageview(self.team, "u1", "github.com")
            _pageview(self.team, "u1", "stripe.com")

            results = list_suggested_urls(team_id=self.team.id, days=30, limit=10)

        assert [r["host"] for r in results] == ["stripe.com"]

    def test_respects_days_window(self) -> None:
        # ClickHouse's now() is server-time, not affected by freeze_time — anchor on real wallclock.
        real_now = datetime.now(tz=ZoneInfo("UTC"))
        _pageview(self.team, "u1", "recent.com", timestamp=real_now - timedelta(days=2))
        _pageview(self.team, "u1", "old.com", timestamp=real_now - timedelta(days=20))

        results_short = list_suggested_urls(team_id=self.team.id, days=7, limit=10)
        results_long = list_suggested_urls(team_id=self.team.id, days=30, limit=10)

        assert {r["host"] for r in results_short} == {"recent.com"}
        assert {r["host"] for r in results_long} == {"recent.com", "old.com"}

    def test_limit_caps_response_even_with_monitored_exclusions(self) -> None:
        Monitor.objects.create(team_id=self.team.id, name="a", url="https://a.com")
        Monitor.objects.create(team_id=self.team.id, name="b", url="https://b.com")

        with freeze_time(NOW):
            for host in ("a.com", "b.com", "c.com", "d.com", "e.com", "f.com"):
                _pageview(self.team, "u1", host)

            results = list_suggested_urls(team_id=self.team.id, days=30, limit=2)

        assert len(results) == 2
        # Excludes a.com and b.com (monitored), leaves c-f, top 2 by ingestion order tie
        assert all(r["host"] not in {"a.com", "b.com"} for r in results)


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
        assert row["uptime_30d"] is None
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
        assert row["uptime_30d"] == 1.0
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

    def test_uptime_30d_is_pings_minus_failures(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="u", url="https://u.io")
        for _ in range(9):
            self._ping(monitor, outcome=PingOutcome.SUCCESS)
        self._ping(monitor, outcome=PingOutcome.FAILURE)

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["uptime_30d"] == 0.9

    def test_handles_no_recent_successes_without_erroring(self) -> None:
        """ClickHouse's avgIf returns NaN when no rows match. Without NaN→None
        normalization the int() conversion downstream raises ValueError and the
        whole summary endpoint 500s, breaking the UI for fresh / down monitors."""
        monitor = Monitor.objects.create(team_id=self.team.id, name="all-failures", url="https://nope.io")
        for _ in range(3):
            self._ping(monitor, outcome=PingOutcome.FAILURE, latency_ms=5000)

        results = list_monitor_summaries(team_id=self.team.id)

        row = next(r for r in results if r["id"] == monitor.id)
        assert row["status"] == "down"
        assert row["avg_latency_24h_ms"] is None
        assert row["uptime_30d"] == 0.0

    def test_orders_by_display_order_then_recency(self) -> None:
        # Created oldest first; without reordering, "newest" (z) would come first.
        a = Monitor.objects.create(team_id=self.team.id, name="a", url="https://a.io")
        z = Monitor.objects.create(team_id=self.team.id, name="z", url="https://z.io")

        reorder_monitors(team_id=self.team.id, ordered_ids=[a.id, z.id])

        results = list_monitor_summaries(team_id=self.team.id)

        assert [r["name"] for r in results] == ["a", "z"]

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
        assert row["uptime_30d"] == 1.0


class TestBulkCreateMonitors(UptimeTeamScopedTestMixin, BaseTest):
    def test_creates_all_atomically(self) -> None:
        items = [
            {"name": "PostHog", "url": "https://posthog.com"},
            {"name": "GitHub", "url": "https://github.com"},
        ]
        created = bulk_create_monitors(team_id=self.team.id, items=items)

        assert len(created) == 2
        assert {m.url for m in Monitor.objects.filter(team_id=self.team.id)} == {
            "https://posthog.com",
            "https://github.com",
        }

    def test_empty_list_creates_nothing(self) -> None:
        created = bulk_create_monitors(team_id=self.team.id, items=[])
        assert created == []
        assert Monitor.objects.filter(team_id=self.team.id).count() == 0


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
        from uuid import uuid4

        delete_monitor(team_id=self.team.id, monitor_id=uuid4())


class TestReorderMonitors(UptimeTeamScopedTestMixin, BaseTest):
    def test_persists_display_order(self) -> None:
        a = Monitor.objects.create(team_id=self.team.id, name="a", url="https://a.io")
        b = Monitor.objects.create(team_id=self.team.id, name="b", url="https://b.io")
        c = Monitor.objects.create(team_id=self.team.id, name="c", url="https://c.io")

        reorder_monitors(team_id=self.team.id, ordered_ids=[c.id, a.id, b.id])

        for monitor in (a, b, c):
            monitor.refresh_from_db()
        assert (c.display_order, a.display_order, b.display_order) == (0, 1, 2)

    def test_ignores_unknown_ids(self) -> None:
        from uuid import uuid4

        a = Monitor.objects.create(team_id=self.team.id, name="a", url="https://a.io")
        bogus = uuid4()

        # Should not raise; unknown id is silently skipped.
        reorder_monitors(team_id=self.team.id, ordered_ids=[bogus, a.id])

        a.refresh_from_db()
        # `a` gets position 1 because the bogus id occupies position 0.
        assert a.display_order == 1


@pytest.mark.django_db
class TestStatusChangeEmission:
    def _make_monitor(self, team):
        return logic.create_monitor(team_id=team.id, name="example", url="https://example.com")

    @patch("products.uptime.backend.logic.produce_internal_event")
    @patch("products.uptime.backend.logic.get_client")
    def test_emits_on_first_ping_when_no_prior_status(self, mock_get_client, mock_produce, team):
        monitor = self._make_monitor(team)
        mock_redis = mock_get_client.return_value
        mock_redis.get.return_value = None

        logic._maybe_emit_status_change(
            team_id=team.id,
            monitor_id=monitor.id,
            new_status=logic.STATUS_UP,
            timestamp=timezone.now(),
            latency_ms=100,
            status_code=200,
        )

        mock_redis.set.assert_called_once_with(logic._status_redis_key(monitor.id), logic.STATUS_UP)
        assert mock_produce.call_count == 1
        event = mock_produce.call_args.kwargs["event"]
        assert event.event == logic.STATUS_CHANGED_EVENT
        assert event.properties["previous_status"] == logic.STATUS_UNKNOWN
        assert event.properties["new_status"] == logic.STATUS_UP
        assert event.properties["monitor_id"] == str(monitor.id)
        assert event.properties["monitor_name"] == "example"

    @patch("products.uptime.backend.logic.produce_internal_event")
    @patch("products.uptime.backend.logic.get_client")
    def test_does_not_emit_when_status_unchanged(self, mock_get_client, mock_produce, team):
        monitor = self._make_monitor(team)
        mock_redis = mock_get_client.return_value
        mock_redis.get.return_value = b"up"

        logic._maybe_emit_status_change(
            team_id=team.id,
            monitor_id=monitor.id,
            new_status=logic.STATUS_UP,
            timestamp=timezone.now(),
            latency_ms=100,
            status_code=200,
        )

        mock_redis.set.assert_not_called()
        mock_produce.assert_not_called()

    @patch("products.uptime.backend.logic.produce_internal_event")
    @patch("products.uptime.backend.logic.get_client")
    def test_emits_on_up_to_down_transition(self, mock_get_client, mock_produce, team):
        monitor = self._make_monitor(team)
        mock_redis = mock_get_client.return_value
        mock_redis.get.return_value = b"up"

        logic._maybe_emit_status_change(
            team_id=team.id,
            monitor_id=monitor.id,
            new_status=logic.STATUS_DOWN,
            timestamp=timezone.now(),
            latency_ms=12000,
            status_code=503,
        )

        mock_redis.set.assert_called_once_with(logic._status_redis_key(monitor.id), logic.STATUS_DOWN)
        event = mock_produce.call_args.kwargs["event"]
        assert event.properties["previous_status"] == logic.STATUS_UP
        assert event.properties["new_status"] == logic.STATUS_DOWN
        assert event.properties["status_code"] == 503
        assert event.properties["latency_ms"] == 12000

    @pytest.mark.parametrize(
        "outcome,expected",
        [(PingOutcome.SUCCESS, logic.STATUS_UP), (PingOutcome.FAILURE, logic.STATUS_DOWN)],
    )
    def test_outcome_to_status_mapping(self, outcome, expected):
        assert logic._outcome_to_status(outcome) == expected
