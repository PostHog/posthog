import json
import datetime as dt
from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.logs.backend.pattern_appearance import LOGS_PATTERN_FEED, _logs_url

T0 = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)


class TestLogsPatternFeed(ClickhouseTestMixin, BaseTest):
    def _bucket(self, at: dt.datetime, pattern: str, severity: str = "error", environment: str = "prod") -> dict:
        return {
            "team_id": self.team.id,
            "time_bucket": at.strftime("%Y-%m-%d %H:%M:%S"),
            "service_name": "api",
            "namespace": "",
            "environment": environment,
            "severity_text": severity,
            "pattern_version": 5,
            "pattern": pattern,
            "log_count": 1,
        }

    def test_reports_each_identity_at_its_first_bucket_in_the_window(self) -> None:
        rows = [
            self._bucket(T0 - dt.timedelta(minutes=5), "Before the window"),
            self._bucket(T0 + dt.timedelta(minutes=10), "Retry <N> timed out", environment="staging"),
            self._bucket(T0, "Retry <N> timed out"),
            self._bucket(T0 + dt.timedelta(minutes=5), "Retry <N> timed out", severity="warn"),
            self._bucket(T0 + dt.timedelta(minutes=30), "After the window"),
        ]
        sync_execute("INSERT INTO logs_pattern_buckets FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        seen = LOGS_PATTERN_FEED.seen(self.team.id, T0, T0 + dt.timedelta(minutes=30), 10)

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
        {"service_name": "api", "severity_text": "error"},
        {"pattern": "Retry <N> timed out", "pattern_version": 5, "first_seen_at": T0.isoformat()},
    )

    query = parse_qs(urlparse(url).query)
    assert json.loads(query["filterGroup"][0])["values"][0]["values"][0]["value"] == ["Retry <N> timed out"]
    assert json.loads(query["dateRange"][0])["date_from"] == (T0 - dt.timedelta(minutes=10)).isoformat()
