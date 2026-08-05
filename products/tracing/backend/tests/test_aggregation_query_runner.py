import datetime as dt

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.logic import run_aggregation_query, run_tree_query
from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Child starts 40ms after its parent. In nanoseconds that's 40_000_000 — the unit the
# avg_start_offset_nano column claims to report.
CHILD_OFFSET_MS = 40
EXPECTED_OFFSET_NANO = CHILD_OFFSET_MS * 1_000_000

MS_TO_NANO = 1_000_000


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


class TestTraceSpansAggregationPercentiles(_TraceSpansTestBase):
    SERVICE = "web"
    NAME = "GET /api/things"
    # (duration_ms, span_count): sized so each percentile of n=1000 lands inside one uniform band.
    BANDS = [(10, 600), (100, 360), (1000, 35), (5000, 5)]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        trace_id = _b64((1).to_bytes(16, "big"))
        base_ts = dt.datetime(2026, 6, 2, 8, 0, 0)
        start_str = base_ts.strftime("%Y-%m-%d %H:%M:%S.%f")

        rows: list[str] = []
        idx = 0
        for duration_ms, count in cls.BANDS:
            end_str = (base_ts + dt.timedelta(milliseconds=duration_ms)).strftime("%Y-%m-%d %H:%M:%S.%f")
            for _ in range(count):
                idx += 1
                span_id = _b64(idx.to_bytes(8, "big"))
                rows.append(
                    f"('019e8760-0000-0000-0000-{idx:012d}', {cls.team.id}, '{trace_id}', "
                    f"'{span_id}', '', '{cls.NAME}', 2, '{start_str}', '{end_str}', '{start_str}', 0, '{cls.SERVICE}')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @parameterized.expand(
        [
            ("p50", "p50_duration_nano", 10 * MS_TO_NANO),
            ("p95", "p95_duration_nano", 100 * MS_TO_NANO),
            ("p99", "p99_duration_nano", 1000 * MS_TO_NANO),
            ("p999", "p999_duration_nano", 5000 * MS_TO_NANO),
        ]
    )
    def test_duration_percentile(self, _name, field, expected_nano):
        response = run_aggregation_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            service_names=[self.SERVICE],
        )
        row = next(r for r in response.results if r.name == self.NAME)
        self.assertAlmostEqual(getattr(row, field), expected_nano, delta=MS_TO_NANO)


class TestTraceSpansTreePercentiles(_TraceSpansTestBase):
    SERVICE = "web"
    PARENT_NAME = "entry-op"
    CHILD_NAME = "GET /api/things"
    # Same banding as the flat test, applied to the 1000 child spans of one (parent → child) edge.
    BANDS = [(10, 600), (100, 360), (1000, 35), (5000, 5)]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        trace_id = _b64((1).to_bytes(16, "big"))
        parent_span_id = _b64((1).to_bytes(8, "big"))
        base_ts = dt.datetime(2026, 6, 2, 8, 0, 0)
        start_str = base_ts.strftime("%Y-%m-%d %H:%M:%S.%f")

        rows = [
            f"('019e8761-0000-0000-0000-000000000000', {cls.team.id}, '{trace_id}', "
            f"'{parent_span_id}', '', '{cls.PARENT_NAME}', 2, '{start_str}', '{start_str}', '{start_str}', 0, '{cls.SERVICE}')"
        ]
        idx = 0
        for duration_ms, count in cls.BANDS:
            end_str = (base_ts + dt.timedelta(milliseconds=duration_ms)).strftime("%Y-%m-%d %H:%M:%S.%f")
            for _ in range(count):
                idx += 1
                child_span_id = _b64((idx + 1).to_bytes(8, "big"))
                rows.append(
                    f"('019e8761-0000-0000-0001-{idx:012d}', {cls.team.id}, '{trace_id}', "
                    f"'{child_span_id}', '{parent_span_id}', '{cls.CHILD_NAME}', 2, '{start_str}', '{end_str}', '{start_str}', 0, '{cls.SERVICE}')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @parameterized.expand(
        [
            ("p50", "p50_duration_nano", 10 * MS_TO_NANO),
            ("p95", "p95_duration_nano", 100 * MS_TO_NANO),
            ("p99", "p99_duration_nano", 1000 * MS_TO_NANO),
            ("p999", "p999_duration_nano", 5000 * MS_TO_NANO),
        ]
    )
    def test_duration_percentile(self, _name, field, expected_nano):
        response = run_tree_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            span_name=self.CHILD_NAME,
            service_name=self.SERVICE,
        )
        edge = next(n for n in response.results if n.name == self.CHILD_NAME)
        self.assertAlmostEqual(getattr(edge, field), expected_nano, delta=MS_TO_NANO)
