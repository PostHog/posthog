import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, TraceSpansQuery

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import TraceSpansQueryRunner

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestExcludeAttributes(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        ts_str = dt.datetime(2026, 6, 2, 8, 0, 0).strftime("%Y-%m-%d %H:%M:%S.%f")
        # `attributes` is an ALIAS over attributes_map_str whose keys carry a `__str` type suffix
        # that left(k, -5) strips — so 'http.method__str' surfaces as 'http.method'.
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str) VALUES "
            "("
            f"'019e8754-0000-0000-0000-000000000001', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
            f"'{_b64((1).to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web', "
            "map('http.method__str', 'POST'))"
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _run(self, *, exclude: bool) -> list[dict]:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="timestamp",
            limit=100,
            excludeAttributes=exclude,
        )
        return TraceSpansQueryRunner(query, self.team).run().results

    @parameterized.expand(
        [
            # excludeAttributes=False keeps the populated attribute map.
            ("included_by_default", False, {"http.method": "POST"}),
            # excludeAttributes=True: key stays present (positional mapping is stable) but the map is empty.
            ("omitted_when_excluded", True, {}),
        ]
    )
    def test_attributes(self, _name, exclude, expected_attributes):
        results = self._run(exclude=exclude)
        self.assertEqual(results[0]["attributes"], expected_attributes)
