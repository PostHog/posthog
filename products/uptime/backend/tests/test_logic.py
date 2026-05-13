from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person

from products.uptime.backend.logic import bulk_create_monitors, list_suggested_urls
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
