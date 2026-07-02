import os
import json
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

_FIXTURE_WINDOW = {"date_from": "2025-12-14T00:00:00Z", "date_to": "2025-12-19T00:00:00Z"}


class TestSparklineApi(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def _sparkline(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/sparkline", data={"query": query_params})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @parameterized.expand(
        [
            ("with_date_range", {"dateRange": _FIXTURE_WINDOW}, 1011),
            # No dateRange/filterGroup — MCP/agent callers routinely omit these optional
            # fields, so defaults must be applied server-side rather than crashing.
            ("defaults_to_last_hour", {}, 0),
        ]
    )
    @freeze_time("2025-12-18T12:00:00Z")
    def test_sparkline(self, _name, query_params, expected_count):
        buckets = self._sparkline(query_params)
        self.assertEqual(sum(bucket["count"] for bucket in buckets), expected_count)
        # Bucket times must serialize timezone-aware so the frontend doesn't misparse them as
        # local time when comparing against the (UTC) live_logs_checkpoint.
        for bucket in buckets:
            self.assertIsNotNone(datetime.fromisoformat(bucket["time"]).tzinfo)
