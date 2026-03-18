import os
import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestSparklineQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)
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

    def _make_sparkline_api_request(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/sparkline", data={"query": query_params})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @freeze_time("2025-12-16T10:33:00Z")
    def test_sparkline_single_log(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16T10:23:16.449937Z", "date_to": "2025-12-16T10:23:16.449937Z"},
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        response = self._make_sparkline_api_request(query_params)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["count"], 1)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_sparkline_near_full(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16T09:00:00.000000Z", "date_to": "2025-12-16T10:31:35.692143Z"},
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        response = self._make_sparkline_api_request(query_params)

        self.assertEqual(len(response), 49)
        self.assertEqual(sum(r["count"] for r in response), 900)
