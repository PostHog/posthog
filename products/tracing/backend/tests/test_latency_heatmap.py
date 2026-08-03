import datetime as dt

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Roots across two 2-minute time buckets (08:00, 08:30) and 1-2-5 duration-bucket boundaries:
# 1.5ms → 1ms bucket, 3ms and 3.5ms → 2ms bucket, 700ms → 500ms bucket. Trace 0 also gets a
# 5s child span, which must not appear in the default heatmap — root durations only.
TRACES = [
    # (timestamp, root duration, child duration, service)
    (dt.datetime(2026, 6, 2, 8, 0, 0), dt.timedelta(milliseconds=1.5), dt.timedelta(seconds=5), "web"),
    (dt.datetime(2026, 6, 2, 8, 0, 0), dt.timedelta(milliseconds=3), None, "web"),
    (dt.datetime(2026, 6, 2, 8, 30, 0), dt.timedelta(milliseconds=3.5), None, "web"),
    (dt.datetime(2026, 6, 2, 8, 30, 0), dt.timedelta(milliseconds=700), None, "api"),
]

MS = 1_000_000  # ns per ms
# The 07:00-09:00 window buckets to 2-minute intervals (~50 target buckets), so these
# timestamps are bucket starts.
T0800 = "2026-06-02T08:00:00+00:00"
T0830 = "2026-06-02T08:30:00+00:00"


class TestTraceSpansLatencyHeatmap(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        rows: list[str] = []
        for i, (timestamp, root_duration, child_duration, service) in enumerate(TRACES):
            trace_id = _b64(i.to_bytes(16, "big"))
            root_span_id = _b64((1000 + i * 2).to_bytes(8, "big"))
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            root_end = (timestamp + root_duration).strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8758-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{root_span_id}', '', "
                f"'GET /api', 2, '{ts_str}', '{root_end}', '{ts_str}', 0, '{service}')"
            )
            if child_duration is not None:
                child_span_id = _b64((1001 + i * 2).to_bytes(8, "big"))
                child_end = (timestamp + child_duration).strftime("%Y-%m-%d %H:%M:%S.%f")
                rows.append(
                    f"('019e8758-0000-0000-0000-{len(rows):012d}', {cls.team.id}, '{trace_id}', '{child_span_id}', "
                    f"'{root_span_id}', 'db query', 2, '{ts_str}', '{child_end}', '{ts_str}', 0, '{service}')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _heatmap(self, **extra_query: object) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, **extra_query}
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/latency-heatmap/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_cells_bucket_root_durations_by_time_and_1_2_5_series(self):
        rows = self._heatmap()
        cells = {(row["time"], row["bucket_ns"]): row["count"] for row in rows if row["count"] > 0}
        self.assertEqual(
            cells,
            {
                (T0800, 1 * MS): 1,  # 1.5ms → 1ms bucket
                (T0800, 2 * MS): 1,  # 3ms → 2ms bucket
                (T0830, 2 * MS): 1,  # 3.5ms → 2ms bucket
                (T0830, 500 * MS): 1,  # 700ms → 500ms bucket
            },
        )
        # Implicit in the equality above, but loud: the 5s child span produces no cell — the
        # default heatmap counts traces by ROOT duration, like the trace list and histogram.

        # Quiet time buckets come back as one {time, bucket_ns: 0, count: 0} sentinel each, so
        # the frontend can enumerate the full x axis without re-deriving the interval logic.
        sentinels = [row for row in rows if row["count"] == 0]
        self.assertTrue(sentinels)
        self.assertTrue(all(row["bucket_ns"] == 0 for row in sentinels))
        self.assertGreater(len({row["time"] for row in rows}), len({time for time, _ in cells}))

    def test_root_spans_false_counts_child_spans_for_operation_scope(self):
        # The operation detail page scopes by span name and needs child spans counted: the 5s
        # 'db query' child (invisible to the root-only heatmap above) must appear, in its
        # trace's time bucket.
        rows = self._heatmap(
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
        cells = {(row["time"], row["bucket_ns"]): row["count"] for row in rows if row["count"] > 0}
        self.assertEqual(cells, {(T0800, 5_000 * MS): 1})

    def test_null_query_body_does_not_crash(self):
        # An explicit `{"query": null}` body must fall back to defaults, not AttributeError into a 500.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/latency-heatmap/",
            {"query": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
