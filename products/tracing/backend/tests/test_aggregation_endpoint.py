import datetime as dt

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.logic import _ROW_LIMIT, DEFAULT_AGGREGATION_ROW_LIMIT
from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase


class TestTraceSpansAggregationEndpoint(_TraceSpansTestBase):
    SERVICE = "web"
    # More distinct (service, name) groups than the default page, so an unbounded response would
    # return the full high-cardinality tail — the payload blow-up this endpoint must cap by default.
    TOTAL_NAMES = DEFAULT_AGGREGATION_ROW_LIMIT + 20

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base_ts = dt.datetime(2026, 6, 2, 8, 0, 0)
        start_str = base_ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for i in range(cls.TOTAL_NAMES):
            # Duration decreases with i so total_duration_nano DESC ordering is deterministic.
            end_str = (base_ts + dt.timedelta(milliseconds=cls.TOTAL_NAMES - i)).strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8770-0000-0000-0000-{i:012d}', {cls.team.id}, '{_b64(i.to_bytes(16, 'big'))}', "
                f"'{_b64(i.to_bytes(8, 'big'))}', '', 'GET /api/thing/{i}', 2, "
                f"'{start_str}', '{end_str}', '{start_str}', 0, '{cls.SERVICE}')"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _aggregate(self, **query_fields) -> dict:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, **query_fields}
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/aggregate/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_default_query_caps_rows_and_reports_more(self):
        data = self._aggregate()
        self.assertEqual(len(data["results"]), DEFAULT_AGGREGATION_ROW_LIMIT)
        self.assertTrue(data["has_more"])
        self.assertEqual(data["next_offset"], DEFAULT_AGGREGATION_ROW_LIMIT)

    def test_explicit_limit_opts_into_the_full_tail(self):
        # The cap is a default, not a hard loss: callers can still page the whole set in.
        data = self._aggregate(limit=_ROW_LIMIT)
        self.assertEqual(len(data["results"]), self.TOTAL_NAMES)
        self.assertFalse(data["has_more"])
        self.assertIsNone(data["next_offset"])

    @parameterized.expand([("first_page", 0), ("second_page", 60)])
    def test_offset_pages_are_disjoint(self, _name, offset):
        page_size = 60
        data = self._aggregate(limit=page_size, offset=offset)
        names = [row["name"] for row in data["results"]]
        self.assertEqual(len(names), len(set(names)))
        expected_more = offset + page_size < self.TOTAL_NAMES
        self.assertEqual(data["has_more"], expected_more)
        self.assertEqual(data["next_offset"], offset + page_size if expected_more else None)
