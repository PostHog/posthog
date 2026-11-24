import json
import datetime as dt
from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.alerts_platform.backend.facade.payload import payload_bytes
from products.logs.backend.pattern_appearance import LOGS_PATTERN_FEED, _identity, _logs_url

T0 = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)


class TestLogsPatternFeed(ClickhouseTestMixin, BaseTest):
    def _bucket(
        self, at: dt.datetime, pattern: str, severity: str = "error", environment: str = "prod", version: int = 5
    ) -> dict:
        return {
            "team_id": self.team.id,
            "time_bucket": at.strftime("%Y-%m-%d %H:%M:%S"),
            "service_name": "api",
            "namespace": "",
            "environment": environment,
            "severity_text": severity,
            "pattern_version": version,
            "pattern": pattern,
            "log_count": 1,
        }

    def test_reports_each_identity_at_its_first_bucket_in_the_window(self) -> None:
        rows = [
            self._bucket(T0 - dt.timedelta(minutes=5), "Before the window"),
            self._bucket(T0 + dt.timedelta(minutes=10), "Retry <N> timed out", environment="staging"),
            self._bucket(T0, "Retry <N> timed out"),
            self._bucket(T0 + dt.timedelta(minutes=5), "Retry <N> timed out", severity="warn"),
            # A new masker that leaves the text alone keeps the identity.
            self._bucket(T0 + dt.timedelta(minutes=10), "Retry <N> timed out", version=6),
            self._bucket(T0 + dt.timedelta(minutes=15), ""),
            self._bucket(T0 + dt.timedelta(minutes=15), "   "),
            self._bucket(T0 + dt.timedelta(minutes=30), "After the window"),
        ]
        sync_execute("INSERT INTO logs_pattern_buckets FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        # The bounds are sighting times, which are bucket ends, so this covers the buckets from T0 to T0+30.
        seen = LOGS_PATTERN_FEED.seen(self.team.id, T0 + dt.timedelta(minutes=5), T0 + dt.timedelta(minutes=35), 10)

        # Dated at the end of each bucket: the first and the last one the identity appeared in.
        assert [(s.labels["pattern"], s.labels["severity_text"], s.seen_at, s.last_seen_at) for s in seen] == [
            ("Retry <N> timed out", "error", T0 + dt.timedelta(minutes=5), T0 + dt.timedelta(minutes=15)),
            ("Retry <N> timed out", "warn", T0 + dt.timedelta(minutes=10), T0 + dt.timedelta(minutes=10)),
        ]
        # The first bucket's environment, not a later one's.
        assert seen[0].labels["environment"] == "prod"
        assert seen[0].identity_key != seen[1].identity_key


def test_the_message_links_to_the_announced_pattern_from_before_its_first_sighting() -> None:
    url = _logs_url(
        2,
        {
            "pattern": "Retry <N> timed out",
            "pattern_complete": True,
            "pattern_version": 5,
            "service_name": "api",
            "severity_text": "error",
            "first_seen_at": T0.isoformat(),
        },
    )

    query = parse_qs(urlparse(url).query)
    assert json.loads(query["filterGroup"][0])["values"][0]["values"][0]["value"] == ["Retry <N> timed out"]
    assert json.loads(query["dateRange"][0])["date_from"] == (T0 - dt.timedelta(minutes=10)).isoformat()
    # The full service name from the detail, not a label cut for display.
    assert json.loads(query["serviceNames"][0]) == ["api"]


def test_a_pattern_too_long_for_a_message_link_falls_back_to_service_and_severity() -> None:
    pattern = "x" * 1700
    url = _logs_url(
        2,
        {"pattern": pattern, "pattern_complete": True, "pattern_version": 5, "service_name": "api"},
    )

    assert len(url) <= 2000
    assert "filterGroup" not in parse_qs(urlparse(url).query)


def test_a_long_wide_character_pattern_keeps_its_detail_inside_the_platform_budget() -> None:
    # The platform measures the detail as ASCII-escaped JSON, where each of these characters takes 6 bytes.
    seen = _identity("api", "error", 5, "接続が切断されました。" * 70, "prod", "", T0, T0)

    # Over 4,096 bytes, the platform drops the whole detail, and the message loses its pattern and link filters.
    assert payload_bytes(seen.detail) <= 4096
    assert seen.detail["pattern_complete"] is False
