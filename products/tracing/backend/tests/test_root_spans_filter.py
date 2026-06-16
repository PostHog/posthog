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
# Trace A (service "web" throughout): root "GET /api" with two children.
ROOT_NAME = "GET /api"
CHILD_NAME = "redis_cluster.discovery"
# Trace B: its root runs on service "worker" (won't match a "web" filter), but a child runs on "web".
OTHER_ROOT_NAME = "POST /webhook"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestRootSpansFilter(ClickhouseTestMixin, APIBaseTest):
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

        trace_a = _b64((1).to_bytes(16, "big"))
        trace_b = _b64((2).to_bytes(16, "big"))
        root_a = _b64((1).to_bytes(8, "big"))
        root_b = _b64((4).to_bytes(8, "big"))
        base = dt.datetime(2026, 6, 2, 8, 0, 0)

        def _row(
            uuid_suffix: int, trace_id: str, span_id: str, parent: str, name: str, service: str, offset_ms: int
        ) -> str:
            ts = base + dt.timedelta(milliseconds=offset_ms)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            return (
                "("
                f"'019e8754-0000-0000-0000-{uuid_suffix:012d}', {cls.team.id}, '{trace_id}', "
                f"'{span_id}', '{parent}', '{name}', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, '{service}'"
                ")"
            )

        rows = [
            # Trace A: root and both children on service "web".
            _row(1, trace_a, root_a, "", ROOT_NAME, "web", 0),
            _row(2, trace_a, _b64((2).to_bytes(8, "big")), root_a, CHILD_NAME, "web", 10),
            _row(3, trace_a, _b64((3).to_bytes(8, "big")), root_a, "clickhouse.query", "web", 20),
            # Trace B: root on "worker" (won't match a "web" filter), child on "web" (will).
            _row(4, trace_b, root_b, "", OTHER_ROOT_NAME, "worker", 0),
            _row(5, trace_b, _b64((5).to_bytes(8, "big")), root_b, CHILD_NAME, "web", 10),
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _run(self, *, root_spans: bool | None, prefetch: int, service_names: list[str] | None = None) -> list[dict]:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="timestamp",
            limit=100,
            rootSpans=root_spans,
            prefetchSpans=prefetch,
            serviceNames=service_names,
        )
        return TraceSpansQueryRunner(query, self.team).run().results

    @parameterized.expand(
        [
            # rootSpans=True selects traces by ROOT match: only trace A (its root is on "web").
            # Trace B is dropped because its root is on "worker", even though a child is on "web".
            ("true_prefetches_children_excludes_nonroot_traces", True, False),
            # rootSpans=False matches a trace on ANY span, so trace B comes through via its "web" child.
            ("false_includes_child_matched_traces", False, True),
            # The frontend sends None; it behaves like False (relies on prefetch for the waterfall).
            ("none_includes_child_matched_traces", None, True),
        ]
    )
    def test_root_spans_filter(self, _name, root_spans, expect_other_trace):
        results = self._run(root_spans=root_spans, prefetch=20, service_names=["web"])
        names = {r["name"] for r in results}
        # Trace A's root always matches the filter, and its children are always prefetched for the
        # waterfall regardless of rootSpans — this is the regression guard for the root_filter fix.
        self.assertIn(ROOT_NAME, names)
        self.assertIn(CHILD_NAME, names)
        if expect_other_trace:
            self.assertIn(OTHER_ROOT_NAME, names)
        else:
            self.assertNotIn(OTHER_ROOT_NAME, names)
