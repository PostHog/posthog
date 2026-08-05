import os
import json
import uuid
from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.urls import get_resolver

from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestSparklineQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Import the URL tree before any test freezes time. Every test here requests under
        # freeze_time, and the first such request is what imports the URL conf — which reaches
        # pydantic.v1, whose ConstrainedDate subclasses `date`. freezegun has swapped that for
        # FakeDate by then, so the import dies with a metaclass conflict and whichever test happens
        # to run first fails.
        assert get_resolver().url_patterns is not None

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

    @freeze_time("2026-03-02T00:10:00Z")
    def test_service_breakdown_over_a_day_is_not_truncated_by_the_row_cap(self):
        # A row is (time bucket × service present in it) and the breakdown isn't capped to a top-N,
        # so a 24h range (30-minute buckets) crosses the old 1000-row cap above ~20 services. Rows
        # come back time-ascending, so the cap dropped the *newest* buckets — silently understating
        # recent volume and any total derived from it.
        service_count = 25
        bucket_count = 48
        self._insert_logs_across_services(
            start="2026-03-01T00:00:00", service_count=service_count, bucket_count=bucket_count
        )

        response = self._make_sparkline_api_request(
            {
                "dateRange": {"date_from": "2026-03-01T00:00:00.000000Z", "date_to": "2026-03-02T00:00:00.000000Z"},
                "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
                "sparklineBreakdownBy": "service",
            }
        )

        self.assertGreater(len(response), 1000)
        self.assertEqual(sum(r["count"] for r in response), service_count * bucket_count)
        # Every service keeps its whole trend rather than losing its later buckets.
        self.assertEqual(len({r["service"] for r in response}), service_count)
        for service in {r["service"] for r in response}:
            self.assertEqual(sum(1 for r in response if r["service"] == service and r["count"] > 0), bucket_count)

    def _insert_logs_across_services(self, start: str, service_count: int, bucket_count: int) -> None:
        """One log per (service, 30-minute bucket), cloned off the fixture so the schema stays valid."""
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            template = json.loads(f.readline())
        start_at = datetime.fromisoformat(start)
        rows = ""
        for service_index in range(service_count):
            for bucket_index in range(bucket_count):
                log_item = dict(template)
                log_item["team_id"] = self.team.id
                log_item["uuid"] = str(uuid.uuid4())
                log_item["service_name"] = f"service-{service_index:03d}"
                # Land mid-bucket so bucket rounding can't move a log into a neighbour.
                timestamp = start_at + timedelta(minutes=30 * bucket_index, seconds=61)
                log_item["timestamp"] = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
                log_item["observed_timestamp"] = log_item["timestamp"]
                rows += json.dumps(log_item) + "\n"
        sync_execute(f"""
            INSERT INTO logs
            FORMAT JSONEachRow
            {rows}
        """)
