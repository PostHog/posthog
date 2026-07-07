import datetime as dt

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Root durations chosen to straddle 1-2-5 bucket boundaries: 1.5ms → 1ms bucket, 3ms and
# 3.5ms → 2ms bucket, 700ms → 500ms bucket. Trace 0 also gets a 5s child span, which must
# not appear anywhere — the histogram counts traces by ROOT duration (what the list shows).
TRACES = [
    # (root duration, child duration, service)
    (dt.timedelta(milliseconds=1.5), dt.timedelta(seconds=5), "web"),
    (dt.timedelta(milliseconds=3), None, "web"),
    (dt.timedelta(milliseconds=3.5), None, "web"),
    (dt.timedelta(milliseconds=700), None, "api"),
]

MS = 1_000_000  # ns per ms


class TestTraceSpansDurationHistogram(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for i, (root_duration, child_duration, service) in enumerate(TRACES):
            trace_id = _b64(i.to_bytes(16, "big"))
            root_span_id = _b64((1000 + i * 2).to_bytes(8, "big"))
            root_end = (base + root_duration).strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8756-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{root_span_id}', '', "
                f"'GET /api', 2, '{ts_str}', '{root_end}', '{ts_str}', 0, '{service}')"
            )
            if child_duration is not None:
                child_span_id = _b64((1001 + i * 2).to_bytes(8, "big"))
                child_end = (base + child_duration).strftime("%Y-%m-%d %H:%M:%S.%f")
                rows.append(
                    f"('019e8756-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{child_span_id}', "
                    f"'{root_span_id}', 'db query', 2, '{ts_str}', '{child_end}', '{ts_str}', 0, '{service}')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _histogram(self, *, service_names: list[str] | None = None, **extra_query: object) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, **extra_query}
        if service_names is not None:
            query["serviceNames"] = service_names
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/duration-histogram/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_buckets_root_durations_on_the_1_2_5_series(self):
        rows = {(row["bucket_ns"], row["service"]): row["count"] for row in self._histogram()}
        self.assertEqual(
            rows,
            {
                (1 * MS, "web"): 1,  # 1.5ms → 1ms bucket
                (2 * MS, "web"): 2,  # 3ms + 3.5ms → 2ms bucket
                (500 * MS, "api"): 1,  # 700ms → 500ms bucket
            },
        )
        # Implicit in the equality above, but make the design constraint loud: the 5s child span
        # must not produce a 5s bucket — only root durations count.

    def test_service_filter_flows_through(self):
        rows = {(row["bucket_ns"], row["service"]): row["count"] for row in self._histogram(service_names=["web"])}
        self.assertEqual(rows, {(1 * MS, "web"): 1, (2 * MS, "web"): 2})

    def test_root_spans_false_counts_child_spans_for_operation_scope(self):
        # The operation detail page scopes by span name and needs child spans counted: the 5s
        # 'db query' child (invisible to the root-only histogram above) must appear.
        rows = {
            (row["bucket_ns"], row["service"]): row["count"]
            for row in self._histogram(
                rootSpans=False,
                filterGroup={
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"type": "span", "key": "name", "operator": "exact", "value": ["db query"]}],
                        }
                    ],
                },
            )
        }
        self.assertEqual(rows, {(5_000 * MS, "web"): 1})


class TestTraceSpansDurationHistogramNullBucket(_TraceSpansTestBase):
    # A clock-skewed span (end_time before timestamp) wraps to a garbage UInt64 duration whose
    # bucket math overflows Int64, so ClickHouse's null-safe toInt returns NULL for that bucket.
    # The histogram must drop it, not 500 on int(None).
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        skewed_end = (base - dt.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
        good_end = (base + dt.timedelta(milliseconds=1.5)).strftime("%Y-%m-%d %H:%M:%S.%f")

        rows = [
            # Clock-skewed root: end_time before timestamp -> overflowing NULL bucket.
            f"('019e8756-0000-0000-0000-000000000000', {cls.team.id}, '{_b64((0).to_bytes(16, 'big'))}', "
            f"'{_b64((1000).to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{skewed_end}', '{ts_str}', 0, 'web')",
            # Healthy root alongside it: must still land in its 1ms bucket.
            f"('019e8756-0000-0000-0000-000000000001', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
            f"'{_b64((1002).to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{good_end}', '{ts_str}', 0, 'web')",
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _histogram(self) -> list[dict]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/duration-histogram/",
            {"query": {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_null_bucket_from_clock_skewed_span_is_dropped(self):
        rows = {(row["bucket_ns"], row["service"]): row["count"] for row in self._histogram()}
        self.assertEqual(rows, {(1 * MS, "web"): 1})
