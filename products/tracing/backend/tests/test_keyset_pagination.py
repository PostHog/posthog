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

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class _TraceSpansTestBase(ClickhouseTestMixin, APIBaseTest):
    # Shared trace_spans table management + query execution. Not collected (no `Test` prefix, no tests).
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def _recreate_trace_spans_tables(cls) -> None:
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

    @classmethod
    def tearDownClass(cls):
        # Restore the standard Python DDL so a later test class in the same process doesn't inherit
        # this class's modified schema. Drop the distributed table first (it depends on the base).
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _execute(self, query: TraceSpansQuery, *, session_timezone: str | None = None) -> list:
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
        settings = {"session_timezone": session_timezone} if session_timezone else None
        return sync_execute(sql, context.values, workload=Workload.LOGS, settings=settings)

    def _ordered_trace_indices(self, *, order_direction: str, limit: int, offset: int = 0) -> list[int]:
        # Distinct trace ids in row order, recovered as the integer trace index from the hex id (col 1).
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="duration",
            orderDirection=order_direction,
            limit=limit,
            offset=offset,
            rootSpans=True,
            prefetchSpans=20,
        )
        ordered: list[int] = []
        for row in self._execute(query):
            idx = int(row[1], 16)
            if idx not in ordered:
                ordered.append(idx)
        return ordered


# 150 same-day root traces (i=0..149), timestamps increasing with i, newest-first ordering.
# The 100th newest is i=50, so page 2 (after that cursor) should yield i=0..49 = 50 distinct traces.
TOTAL_TRACES = 150
PAGE_SIZE = 100
CURSOR_INDEX = 50
CURSOR_TS_ISO = "2026-06-02T08:00:50+00:00"
CURSOR_TRACE_ID_HEX = format(CURSOR_INDEX, "032x")


class TestTraceSpansKeysetPaginationTimezone(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

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

    def _cursor(self) -> str:
        return base64.b64encode(
            json.dumps({"timestamp": CURSOR_TS_ISO, "trace_id": CURSOR_TRACE_ID_HEX}).encode("utf-8")
        ).decode("utf-8")

    def _distinct_trace_count(self, *, after: str | None, limit: int, session_timezone: str) -> int:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="timestamp",
            orderDirection="DESC",
            limit=limit,
            after=after,
            rootSpans=True,
            prefetchSpans=20,
        )
        return len({row[1] for row in self._execute(query, session_timezone=session_timezone)})  # col 1 = hex(trace_id)

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
        self.assertEqual(
            self._distinct_trace_count(after=after, limit=limit, session_timezone=session_timezone), expected
        )


# 20 traces (i=0..19), one root span each, duration = (i+1)s — so duration strictly increases with i.
DURATION_TRACES = 20


class TestTraceSpansDurationOrdering(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        rows = []
        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        for i in range(DURATION_TRACES):
            end = base + dt.timedelta(seconds=i + 1)  # duration = (i+1)s, distinct and non-zero
            end_str = end.strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                "("
                f"'019e8754-0000-0000-0000-{i:012d}', {cls.team.id}, '{_b64(i.to_bytes(16, 'big'))}', "
                f"'{_b64(i.to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, 'web'"
                ")"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @parameterized.expand(
        [
            # Duration increases with i: DESC ranks highest index first, ASC lowest first.
            ("slowest_desc", "DESC", list(range(DURATION_TRACES - 1, -1, -1))),
            ("fastest_asc", "ASC", list(range(DURATION_TRACES))),
        ]
    )
    def test_orders_by_duration(self, _name, order_direction, expected):
        self.assertEqual(self._ordered_trace_indices(order_direction=order_direction, limit=DURATION_TRACES), expected)

    def test_offset_paginates_the_duration_sort(self):
        page_size = 5
        page1 = self._ordered_trace_indices(order_direction="DESC", limit=page_size, offset=0)
        page2 = self._ordered_trace_indices(order_direction="DESC", limit=page_size, offset=page_size)
        self.assertEqual(page1, [19, 18, 17, 16, 15])
        self.assertEqual(page2, [14, 13, 12, 11, 10])

    def _api_page(self, *, limit: int, offset: int) -> tuple[list[int], bool, str | None]:
        # Hits the real endpoint so the VIEW's pagination (limit+1 over-fetch, hasMore, keep-top-N,
        # offset) is exercised end-to-end — the runner-level tests above don't cover that layer.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/query/",
            {
                "query": {
                    "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                    "orderBy": "duration",
                    "orderDirection": "DESC",
                    "limit": limit,
                    "offset": offset,
                    "rootSpans": True,
                    "prefetchSpans": 20,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        ordered: list[int] = []
        for span in body["results"]:
            idx = int(span["trace_id"], 16)
            if idx not in ordered:
                ordered.append(idx)
        return ordered, body["hasMore"], body.get("nextCursor")

    def test_offset_pagination_covers_every_trace_exactly_once(self):
        # Walk the whole list the way the frontend does — advance offset by the running trace count
        # (frontend sends `offset: rootSpans.length`) until hasMore is false — and prove every trace
        # appears exactly once, slowest-first, with no overlap or gap across page boundaries.
        # page_size = 7 deliberately doesn't divide 20 evenly, to stress the ragged final page.
        page_size = 7
        seen: list[int] = []
        page_count = 0
        has_more = True
        first_cursor: str | None = "unset"
        while has_more:
            page, has_more, cursor = self._api_page(limit=page_size, offset=len(seen))
            if page_count == 0:
                first_cursor = cursor
            self.assertGreater(len(page), 0, "a non-final page must never come back empty")
            seen.extend(page)
            page_count += 1
            self.assertLess(page_count, DURATION_TRACES, "pagination did not terminate")

        # Exact equality proves all three at once: full coverage (no drops), no duplicates (no
        # overlap), and correct slowest-first order across every page boundary.
        self.assertEqual(seen, list(range(DURATION_TRACES - 1, -1, -1)))
        self.assertEqual(len(seen), len(set(seen)))  # explicit no-overlap assertion
        self.assertEqual(page_count, 3)  # 7 + 7 + 6
        self.assertIsNone(first_cursor)  # duration ordering paginates by offset, not a keyset cursor


# Each trace has a root span + one child. Trace 1's child (50s) dwarfs its root (5s), so the
# whole-trace max duration disagrees with the root-span duration. With rootSpans=True the list
# displays the root span, so slowest/fastest must rank by ROOT duration, not the longest child.
ROOT_DURATIONS = [10, 5, 8]  # seconds, per trace i=0,1,2 → root order desc = [0, 2, 1]
CHILD_DURATIONS = [1, 50, 2]  # trace 1's child is the longest span anywhere


class TestTraceSpansDurationRootScope(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for i in range(3):
            trace_id = _b64(i.to_bytes(16, "big"))
            # Non-zero span ids so the child's parent_span_id never base64-encodes to all-'A'
            # (which the is_root_span expression would misread as a root).
            root_span_id = _b64((1000 + i * 2).to_bytes(8, "big"))
            child_span_id = _b64((1001 + i * 2).to_bytes(8, "big"))
            root_end = (base + dt.timedelta(seconds=ROOT_DURATIONS[i])).strftime("%Y-%m-%d %H:%M:%S.%f")
            child_end = (base + dt.timedelta(seconds=CHILD_DURATIONS[i])).strftime("%Y-%m-%d %H:%M:%S.%f")
            # Root span: empty parent_span_id → is_root_span = 1.
            rows.append(
                f"('019e8755-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{root_span_id}', '', "
                f"'GET /api', 2, '{ts_str}', '{root_end}', '{ts_str}', 0, 'web')"
            )
            # Child span: parent_span_id = root → is_root_span = 0.
            rows.append(
                f"('019e8755-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{child_span_id}', "
                f"'{root_span_id}', 'db query', 2, '{ts_str}', '{child_end}', '{ts_str}', 0, 'web')"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @parameterized.expand(
        [
            # Root durations [10, 5, 8] → DESC = [0, 2, 1], ASC = [1, 2, 0]. Trace 1's 50s child must
            # NOT change the rank (that would be ranking by whole-trace max, not the displayed root).
            ("slowest_by_root", "DESC", [0, 2, 1]),
            ("fastest_by_root", "ASC", [1, 2, 0]),
        ]
    )
    def test_ranks_by_root_span_duration(self, _name, order_direction, expected):
        self.assertEqual(self._ordered_trace_indices(order_direction=order_direction, limit=10), expected)
