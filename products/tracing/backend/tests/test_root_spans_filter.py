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
# One trace: a root ("GET /api") with two children ("redis_cluster.discovery", "clickhouse.query").
ROOT_NAME = "GET /api"
CHILD_NAME = "redis_cluster.discovery"


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

        trace_id = _b64((1).to_bytes(16, "big"))
        root_span_id = _b64((1).to_bytes(8, "big"))
        base = dt.datetime(2026, 6, 2, 8, 0, 0)

        def _row(uuid_suffix: int, span_id: str, parent: str, name: str, offset_ms: int) -> str:
            ts = base + dt.timedelta(milliseconds=offset_ms)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            return (
                "("
                f"'019e8754-0000-0000-0000-{uuid_suffix:012d}', {cls.team.id}, '{trace_id}', "
                f"'{span_id}', '{parent}', '{name}', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web'"
                ")"
            )

        rows = [
            _row(1, root_span_id, "", ROOT_NAME, 0),
            _row(2, _b64((2).to_bytes(8, "big")), root_span_id, CHILD_NAME, 10),
            _row(3, _b64((3).to_bytes(8, "big")), root_span_id, "clickhouse.query", 20),
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

    def _run(self, *, root_spans: bool | None, prefetch: int) -> list[dict]:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="latest",
            limit=100,
            rootSpans=root_spans,
            prefetchSpans=prefetch,
        )
        return TraceSpansQueryRunner(query, self.team).run().results

    @parameterized.expand(
        [
            # rootSpans=True collapses to the single root span even with a high prefetch.
            ("true_returns_only_root", True, True),
            # rootSpans=False keeps children so the child span (redis_cluster.discovery) comes through.
            ("false_includes_children", False, False),
            # The frontend sends None; it relies on prefetch to populate the waterfall (children present).
            ("none_unchanged_includes_children", None, False),
        ]
    )
    def test_root_spans_filter(self, _name, root_spans, expect_only_root):
        results = self._run(root_spans=root_spans, prefetch=20)
        names = {r["name"] for r in results}
        if expect_only_root:
            self.assertEqual([r["name"] for r in results], [ROOT_NAME])
            self.assertTrue(all(r["is_root_span"] for r in results))
        else:
            self.assertIn(CHILD_NAME, names)
            self.assertIn(ROOT_NAME, names)
