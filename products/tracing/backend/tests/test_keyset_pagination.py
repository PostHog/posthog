import json
import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, TraceSpansQuery

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import TraceSpansQueryRunner

# 150 same-day root traces (i=0..149), timestamps increasing with i, newest-first ordering.
# The 100th newest is i=50, so page 2 (after that cursor) should yield i=0..49 = 50 distinct traces.
TOTAL_TRACES = 150
PAGE_SIZE = 100
CURSOR_INDEX = 50
DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
CURSOR_TS_ISO = "2026-06-02T08:00:50+00:00"
CURSOR_TRACE_ID_HEX = format(CURSOR_INDEX, "032x")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestTraceSpansKeysetPaginationTimezone(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        # is_root_span ships via a separate logs-cluster migration, not the Python DDL.
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        rows = []
        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        for i in range(TOTAL_TRACES):
            ts = base + dt.timedelta(seconds=i)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                "("
                f"'019e8754-0000-0000-0000-{i:012d}', {cls.team.id}, '{_b64(i.to_bytes(16, 'big'))}', "
                f"'{_b64(i.to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web'"
                ")"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        # Restore the standard Python DDL so a later test class in the same process doesn't inherit
        # this class's modified schema. Drop the distributed table first (it depends on the base).
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _cursor(self) -> str:
        return base64.b64encode(
            json.dumps({"timestamp": CURSOR_TS_ISO, "trace_id": CURSOR_TRACE_ID_HEX}).encode("utf-8")
        ).decode("utf-8")

    def _distinct_trace_count(self, *, after: str | None, limit: int, session_timezone: str) -> int:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="latest",
            limit=limit,
            after=after,
            rootSpans=True,
            prefetchSpans=20,
        )
        runner = TraceSpansQueryRunner(query, self.team)
        sql, context = HogQLQueryExecutor(
            query_type="TraceSpansQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=LimitContext.QUERY,
        ).generate_clickhouse_sql()
        results = sync_execute(
            sql, context.values, workload=Workload.LOGS, settings={"session_timezone": session_timezone}
        )
        return len({row[1] for row in results})  # col 1 = hex(trace_id)

    # The regression: a non-UTC session truncated time_bucket on a different day grid and emptied
    # page 2. Both pages must return identical counts under UTC and a non-UTC session. Page 2 passes
    # limit+1 because the view over-fetches one trace to compute has_more.
    @parameterized.expand(
        [
            ("page1_utc", False, PAGE_SIZE, "UTC", PAGE_SIZE),
            ("page1_non_utc", False, PAGE_SIZE, "US/Pacific", PAGE_SIZE),
            ("page2_utc", True, PAGE_SIZE + 1, "UTC", TOTAL_TRACES - PAGE_SIZE),
            ("page2_non_utc", True, PAGE_SIZE + 1, "US/Pacific", TOTAL_TRACES - PAGE_SIZE),
        ]
    )
    def test_keyset_pagination_is_timezone_robust(self, _name, paginated, limit, session_timezone, expected):
        after = self._cursor() if paginated else None
        assert self._distinct_trace_count(after=after, limit=limit, session_timezone=session_timezone) == expected
