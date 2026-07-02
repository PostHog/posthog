import datetime as dt

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Root-only spans across two time buckets. The 08:30 pair carries OTel status Error (2) so the
# error-trend workflow (statusCodes=[2]) has a distinct bucket to land in.
SPANS = [
    # (timestamp, service, status_code)
    (dt.datetime(2026, 6, 2, 8, 0, 0), "web", 0),
    (dt.datetime(2026, 6, 2, 8, 0, 1), "web", 0),
    (dt.datetime(2026, 6, 2, 8, 0, 2), "web", 0),
    (dt.datetime(2026, 6, 2, 8, 0, 3), "web", 0),
    (dt.datetime(2026, 6, 2, 8, 30, 0), "web", 2),
    (dt.datetime(2026, 6, 2, 8, 30, 1), "web", 2),
    (dt.datetime(2026, 6, 2, 8, 0, 0), "api", 0),
]


class TestTraceSpansSparkline(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

    def setUp(self):
        super().setUp()
        # ClickHouse rows aren't rolled back between tests, and the table is recreated only once per
        # class. Truncate and re-seed the base spans each test so the per-test inserts below
        # (childsvc / multirootsvc) stay isolated instead of leaking into sibling tests' counts.
        sync_execute("TRUNCATE TABLE trace_spans")
        rows: list[str] = []
        for i, (timestamp, service, status_code) in enumerate(SPANS):
            trace_id = _b64(i.to_bytes(16, "big"))
            span_id = _b64((1000 + i).to_bytes(8, "big"))
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8757-0000-0000-0000-{i:012d}', {self.team.id}, '{trace_id}', '{span_id}', '', "
                f"'GET /api', 2, '{ts_str}', '{ts_str}', '{ts_str}', {status_code}, '{service}')"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _sparkline(
        self,
        *,
        service_names: list[str] | None = None,
        status_codes: list[int] | None = None,
        root_spans: bool | None = None,
    ) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}}
        if service_names is not None:
            query["serviceNames"] = service_names
        if status_codes is not None:
            query["statusCodes"] = status_codes
        if root_spans is not None:
            query["rootSpans"] = root_spans
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/sparkline/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_returns_zero_filled_time_series_of_span_counts(self):
        rows = self._sparkline()
        self.assertEqual({"time", "service", "count"}, set(rows[0].keys()))
        self.assertEqual(sum(row["count"] for row in rows), len(SPANS))
        # Buckets cover the whole window, so the quiet stretches yield zero-count rows and the
        # seeded spans land in more than one bucket.
        self.assertGreater(len({row["time"] for row in rows}), 1)
        self.assertTrue(any(row["count"] == 0 for row in rows))

    def test_status_codes_filter_is_otel_status_not_http(self):
        rows = self._sparkline(status_codes=[2])
        self.assertEqual(sum(row["count"] for row in rows), 2)
        self.assertTrue(all(row["service"] == "web" for row in rows if row["count"] > 0))
        # HTTP-looking codes match nothing — the column is OTel status (0/1/2).
        rows = self._sparkline(status_codes=[500, 503])
        self.assertEqual(sum(row["count"] for row in rows), 0)

    def test_service_filter_flows_through(self):
        rows = self._sparkline(service_names=["web"])
        self.assertEqual(sum(row["count"] for row in rows), 6)

    def test_root_spans_counts_only_root_spans(self):
        # One trace on its own service: 1 root + 2 children. Spans mode counts all 3 spans; rootSpans
        # (Traces mode) counts only the root — matching the root-match list and the trace count label.
        trace_id = _b64((900).to_bytes(16, "big"))
        root_span_id = _b64((9000).to_bytes(8, "big"))
        ts = "2026-06-02 08:15:00.000000"
        spans = [
            (root_span_id, ""),  # root: empty parent → is_root_span = 1
            (_b64((9001).to_bytes(8, "big")), root_span_id),  # child
            (_b64((9002).to_bytes(8, "big")), root_span_id),  # child
        ]
        rows = [
            f"('019e8757-0000-0000-0000-{9000 + i:012d}', {self.team.id}, '{trace_id}', '{span_id}', "
            f"'{parent}', 'op', 2, '{ts}', '{ts}', '{ts}', 0, 'childsvc')"
            for i, (span_id, parent) in enumerate(spans)
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["childsvc"])), 3)
        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["childsvc"], root_spans=True)), 1)

    def test_root_spans_counts_distinct_traces_not_root_rows(self):
        # A malformed trace with TWO root spans (both empty parent_span_id). Spans mode counts both
        # spans (2); Traces mode must count the trace once (1) — it counts distinct traces, like the
        # "N traces matching filters" label, not root-span rows.
        trace_id = _b64((901).to_bytes(16, "big"))
        ts = "2026-06-02 08:20:00.000000"
        spans = [
            (_b64((9100).to_bytes(8, "big")), ""),  # root 1
            (_b64((9101).to_bytes(8, "big")), ""),  # root 2, same trace_id
        ]
        rows = [
            f"('019e8757-0000-0000-0000-{9100 + i:012d}', {self.team.id}, '{trace_id}', '{span_id}', "
            f"'{parent}', 'op', 2, '{ts}', '{ts}', '{ts}', 0, 'multirootsvc')"
            for i, (span_id, parent) in enumerate(spans)
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["multirootsvc"])), 2)
        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["multirootsvc"], root_spans=True)), 1)


class TestTraceSpansSparklineWithoutIsRootSpanColumn(_TraceSpansTestBase):
    # `is_root_span` is a MATERIALIZED column that ships via a separate logs-cluster migration, not the
    # tracked Python DDL, so it can be absent from trace_spans during a schema rollout. The traces-mode
    # sparkline (rootSpans=True, the endpoint default) must still run instead of raising a ClickHouse
    # "no column is_root_span" error — it derives is_root_span inline from parent_span_id.
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Create only the tracked DDL (no ALTER adding is_root_span), so the column is genuinely
        # missing — unlike the other tracing tests, which add it to mirror production.
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE trace_spans")
        # One trace: a root span (empty parent) plus a child.
        trace_id = _b64((700).to_bytes(16, "big"))
        root_span_id = _b64((7000).to_bytes(8, "big"))
        ts = "2026-06-02 08:00:00.000000"
        spans = [(root_span_id, ""), (_b64((7001).to_bytes(8, "big")), root_span_id)]
        rows = [
            f"('019e8757-0000-0000-0000-{7000 + i:012d}', {self.team.id}, '{trace_id}', '{span_id}', "
            f"'{parent}', 'op', 2, '{ts}', '{ts}', '{ts}', 0, 'rootless')"
            for i, (span_id, parent) in enumerate(spans)
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _sparkline(self, *, service_names: list[str], root_spans: bool | None = None) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, "serviceNames": service_names}
        if root_spans is not None:
            query["rootSpans"] = root_spans
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/sparkline/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_traces_mode_sparkline_runs_without_is_root_span_column(self):
        # Spans mode counts both spans; traces mode counts the single distinct trace via its root —
        # and, crucially, neither query references the absent physical is_root_span column.
        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["rootless"])), 2)
        self.assertEqual(sum(r["count"] for r in self._sparkline(service_names=["rootless"], root_spans=True)), 1)
