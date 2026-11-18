import os
import json

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import ANY, patch

from parameterized import parameterized
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

    @parameterized.expand([(False, 10), (True, 10), (True, 2), (None, 10)])
    @time_machine.travel("2026-06-23T13:00:00Z", tick=False)
    def test_patterns_endpoint_returns_mined_patterns(self, stored_patterns: bool | None, max_examples: int) -> None:
        self._insert(
            [
                {
                    "timestamp": "2026-06-23 12:00:00.000000",
                    "body": f"User {name} not found",
                    "severity_text": "error",
                    "service_name": "auth",
                    "pattern": f"User {name} not found",
                    "pattern_version": 3,
                }
                for name in ("alice", "bob", "carol")
            ]
        )

        with (
            patch("posthoganalytics.feature_enabled", return_value=stored_patterns) as feature_enabled,
            patch.dict(os.environ, {"LOGS_PATTERNS_MAX_EXAMPLES": str(max_examples)}),
        ):
            body = self._request(
                {
                    "dateRange": {"date_from": "2026-06-23T00:00:00Z", "date_to": "2026-06-23T13:00:00Z"},
                    "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
                }
            )

        feature_enabled.assert_any_call(
            "logs_patterns_query_v2",
            str(self.user.distinct_id),
            person_properties={"email": self.user.email, "team_id": str(self.team.pk), "region": ANY},
            groups={"organization": str(self.team.organization_id)},
            group_properties={"organization": {"id": str(self.team.organization_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
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
        examples = {example["body"] for example in pattern["examples"]}
        assert len(pattern["examples"]) == min(3, max_examples)
        assert examples <= {f"User {name} not found" for name in ("alice", "bob", "carol")}
        if max_examples >= 3:
            assert examples == {f"User {name} not found" for name in ("alice", "bob", "carol")}
        assert body["source"] == ("stored_patterns" if stored_patterns else "body_mining")
        assert body["pattern_version"] == (3 if stored_patterns else None)
        assert body["fallback_reason"] == (None if stored_patterns else "flag_disabled")
        assert pattern["match_patterns"] == (
            [f"User {name} not found" for name in ("alice", "bob", "carol")] if stored_patterns else []
        )

    @time_machine.travel("2026-06-23T13:00:00Z", tick=False)
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
