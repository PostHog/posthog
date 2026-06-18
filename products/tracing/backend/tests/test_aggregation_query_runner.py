import datetime as dt

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.logic import run_tree_query
from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Child starts 40ms after its parent. In nanoseconds that's 40_000_000 — the unit the
# avg_start_offset_nano column claims to report.
CHILD_OFFSET_MS = 40
EXPECTED_OFFSET_NANO = CHILD_OFFSET_MS * 1_000_000


class TestTraceSpansTreeStartOffset(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

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


class TestTraceSpansTreeCallRatio(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        # Two traces, each: one entry-op root fanning out to three child-op spans. The
        # (entry-op → child-op) edge counts 6 children over 2 parent invocations → ratio 3.
        ts_str = dt.datetime(2026, 6, 2, 8, 0, 0).strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for trace_no in (1, 2):
            trace_id = _b64(trace_no.to_bytes(16, "big"))
            root_span_id = _b64((trace_no * 100).to_bytes(8, "big"))
            rows.append(
                f"('019e875a-0000-0000-{trace_no:04d}-000000000000', {cls.team.id}, '{trace_id}', "
                f"'{root_span_id}', '', 'entry-op', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web')"
            )
            for child_no in range(1, 4):
                child_span_id = _b64((trace_no * 100 + child_no).to_bytes(8, "big"))
                rows.append(
                    f"('019e875a-0000-0000-{trace_no:04d}-{child_no:012d}', {cls.team.id}, '{trace_id}', "
                    f"'{child_span_id}', '{root_span_id}', 'child-op', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def test_fan_out_edge_reports_calls_per_parent_invocation(self):
        response = run_tree_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            span_name="entry-op",
            service_name="web",
        )
        child_edge = next(node for node in response.results if node.name == "child-op")
        self.assertEqual(child_edge.count, 6)
        self.assertEqual(child_edge.calls_per_parent_invocation, 3.0)

    def test_root_edge_has_no_parent_invocation_ratio(self):
        response = run_tree_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            span_name="entry-op",
            service_name="web",
        )
        root_edge = next(node for node in response.results if node.parent_name == "<ROOT>")
        self.assertIsNone(root_edge.calls_per_parent_invocation)
