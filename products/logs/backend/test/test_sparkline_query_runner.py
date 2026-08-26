import os
import json
import uuid
from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.urls import get_resolver

from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL

from products.logs.backend.sparkline_query_runner import SPARKLINE_TOP_BREAKDOWN_VALUES


class TestSparklineQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    # 25 services over a full day. Before the rollup this was (49 buckets × 25 services) = 1225
    # rows, past the 1000-row cap. Ranked by count every service ties, so the tiebreak on name puts
    # service-000..009 in the top 10; service-024 instead carries almost all of the bytes.
    SERVICE_COUNT = 25
    BUCKET_COUNT = 48
    HEAVY_SERVICE = "service-024"
    BYTES_PER_LOG = 1
    HEAVY_BYTES_PER_LOG = 1_000_000

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

        # Inserted once for the class, not per test: ClickHouse rows aren't rolled back between
        # test methods, so inserting this from each test would double the volume the later ones see.
        cls._insert_logs_across_services(
            start="2026-03-01T00:00:00",
            bucket_count=cls.BUCKET_COUNT,
            services={
                name: (cls.HEAVY_BYTES_PER_LOG if name == cls.HEAVY_SERVICE else cls.BYTES_PER_LOG)
                for name in (f"service-{i:03d}" for i in range(cls.SERVICE_COUNT))
            },
        )

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

    def _service_sparkline(self, rank_by: str | None = None) -> list:
        query_params = {
            "dateRange": {"date_from": "2026-03-01T00:00:00.000000Z", "date_to": "2026-03-02T00:00:00.000000Z"},
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "sparklineBreakdownBy": "service",
        }
        if rank_by is not None:
            query_params["sparklineRankBy"] = rank_by
        return self._make_sparkline_api_request(query_params)

    @freeze_time("2026-03-02T00:10:00Z")
    def test_service_breakdown_collapses_the_tail_into_one_other_bucket(self):
        response = self._service_sparkline()

        breakdowns = {r["service"] for r in response}
        # Top 10 keep their own series and everything else folds into one row per bucket, so the
        # response is bounded by buckets × 11 however many services exist.
        self.assertEqual(len(breakdowns), SPARKLINE_TOP_BREAKDOWN_VALUES + 1)
        self.assertIn(BREAKDOWN_OTHER_STRING_LABEL, breakdowns)
        self.assertLess(len(response), 1000)
        # Collapsing must not lose volume — the folded services are summed, not dropped.
        self.assertEqual(sum(r["count"] for r in response), self.SERVICE_COUNT * self.BUCKET_COUNT)
        folded_count = self.SERVICE_COUNT - SPARKLINE_TOP_BREAKDOWN_VALUES
        self.assertEqual(
            sum(r["count"] for r in response if r["service"] == BREAKDOWN_OTHER_STRING_LABEL),
            folded_count * self.BUCKET_COUNT,
        )

    @freeze_time("2026-03-02T00:10:00Z")
    def test_rank_by_bytes_keeps_a_different_top_ten_than_rank_by_count(self):
        # Every service logs the same number of times, but one carries a million-fold more bytes per
        # log. A caller charting bytes has to see that service as its own series; ranking by count
        # would bury the single biggest contributor to the storage projection inside "other".
        by_count = {r["service"] for r in self._service_sparkline(rank_by="count")}
        by_bytes = {r["service"] for r in self._service_sparkline(rank_by="bytes")}

        self.assertNotIn(self.HEAVY_SERVICE, by_count)
        self.assertIn(self.HEAVY_SERVICE, by_bytes)

        expected_bytes = self.BUCKET_COUNT * (self.HEAVY_BYTES_PER_LOG + (self.SERVICE_COUNT - 1) * self.BYTES_PER_LOG)
        for rank_by in ("count", "bytes"):
            response = self._service_sparkline(rank_by=rank_by)
            self.assertEqual(sum(r["bytes_uncompressed"] for r in response), expected_bytes, rank_by)

    @classmethod
    def _insert_logs_across_services(cls, start: str, bucket_count: int, services: dict[str, int]) -> None:
        """One log per (service, 30-minute bucket), cloned off the fixture so the schema stays valid.

        `services` maps service name to the uncompressed byte size charged to each of its logs.
        """
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            template = json.loads(f.readline())
        start_at = datetime.fromisoformat(start)
        rows = ""
        for service_name, bytes_per_log in services.items():
            for bucket_index in range(bucket_count):
                log_item = dict(template)
                log_item["team_id"] = cls.team.id
                log_item["uuid"] = str(uuid.uuid4())
                log_item["service_name"] = service_name
                log_item["_bytes_uncompressed"] = bytes_per_log
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
