import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestPatternsAPI(ClickhouseTestMixin, APIBaseTest):
    def _insert(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

    def _request(self, query: dict, expected_status: int = status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/patterns", data={"query": query})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @freeze_time("2026-06-23T13:00:00Z")
    def test_patterns_endpoint_returns_mined_patterns(self) -> None:
        self._insert(
            [
                {
                    "timestamp": "2026-06-23 12:00:00.000000",
                    "body": f"User {name} not found",
                    "severity_text": "error",
                    "service_name": "auth",
                }
                for name in ("alice", "bob", "carol")
            ]
        )

        body = self._request(
            {
                "dateRange": {"date_from": "2026-06-23T00:00:00Z", "date_to": "2026-06-23T13:00:00Z"},
                "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            }
        )

        assert body["scanned_count"] == 3
        assert body["total_count"] == 3
        assert body["sampled"] is False
        assert body["sample_coverage_pct"] == 100.0
        pattern = next(p for p in body["patterns"] if p["pattern"] == "User <*> not found")
        assert pattern["count"] == 3
        assert pattern["estimated_count"] == 3
        assert pattern["error_count"] == 3
        assert pattern["estimated_error_count"] == 3
        assert pattern["services"] == ["auth"]

    @freeze_time("2026-06-23T13:00:00Z")
    def test_patterns_endpoint_accepts_flat_filter_group(self) -> None:
        self._insert(
            [
                {
                    "timestamp": "2026-06-23 12:00:00.000000",
                    "body": "db connection failed",
                    "severity_text": "error",
                    "service_name": "api",
                },
                {
                    "timestamp": "2026-06-23 12:01:00.000000",
                    "body": "cache warmed",
                    "severity_text": "info",
                    "service_name": "api",
                },
            ]
        )

        body = self._request(
            {
                "dateRange": {"date_from": "2026-06-23T00:00:00Z", "date_to": "2026-06-23T13:00:00Z"},
                "filterGroup": [{"key": "message", "type": "log", "operator": "icontains", "value": "connection"}],
            }
        )

        assert body["scanned_count"] == 1
        assert body["total_count"] == 1
