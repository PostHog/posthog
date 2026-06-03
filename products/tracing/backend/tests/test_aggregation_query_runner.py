import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import run_tree_query

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
# Child starts 40ms after its parent. In nanoseconds that's 40_000_000 — the unit the
# avg_start_offset_nano column claims to report.
CHILD_OFFSET_MS = 40
EXPECTED_OFFSET_NANO = CHILD_OFFSET_MS * 1_000_000


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestTraceSpansTreeStartOffset(ClickhouseTestMixin, APIBaseTest):
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

        trace_id = _b64((1).to_bytes(16, "big"))
        parent_span_id = _b64((1).to_bytes(8, "big"))
        child_span_id = _b64((2).to_bytes(8, "big"))
        parent_ts = dt.datetime(2026, 6, 2, 8, 0, 0)
        child_ts = parent_ts + dt.timedelta(milliseconds=CHILD_OFFSET_MS)

        def _row(uuid_suffix: int, span_id: str, parent: str, name: str, ts: dt.datetime) -> str:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            return (
                "("
                f"'019e8754-0000-0000-0000-{uuid_suffix:012d}', {cls.team.id}, '{trace_id}', "
                f"'{span_id}', '{parent}', '{name}', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web'"
                ")"
            )

        rows = [
            _row(1, parent_span_id, "", "parent-op", parent_ts),
            _row(2, child_span_id, parent_span_id, "child-op", child_ts),
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

    @parameterized.expand(
        [
            # Pre-fix the child returned ~0.04 (seconds), not 40_000_000 (nanos).
            ("child_offset_in_nanoseconds", "child-op", float(EXPECTED_OFFSET_NANO)),
            ("root_offset_is_zero", "parent-op", 0.0),
        ]
    )
    def test_avg_start_offset(self, _name, edge_name, expected_offset_nano):
        response = run_tree_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            span_name="child-op",
            service_name="web",
        )
        edge = next(node for node in response.results if node.name == edge_name)
        self.assertEqual(edge.avg_start_offset_nano, expected_offset_nano)
