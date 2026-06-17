import datetime as dt

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import _b64, _TraceSpansTestBase

MS = 1_000_000  # ns per ms
BASE = dt.datetime(2026, 6, 2, 8, 0, 0)

# Trace 1 — overlapping children: root spans 1s; child A covers 0-100ms, child B 50-150ms.
# Their union is 150ms, so root self-time is 850ms (interval union, not a 200ms sum).
# Trace 2 — parallel children: both cover 0-100ms exactly; union is 100ms, so root
# self-time is 900ms (a sum would wrongly say 800ms).
TRACES = {
    1: [
        # (span_no, parent_no | None, start_offset_ms, duration_ms)
        (1, None, 0, 1000),
        (2, 1, 0, 100),
        (3, 1, 50, 100),
    ],
    2: [
        (1, None, 0, 1000),
        (2, 1, 0, 100),
        (3, 1, 0, 100),
    ],
}


class TestTraceSelfTime(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        rows: list[str] = []
        for trace_no, spans in TRACES.items():
            trace_id = _b64(trace_no.to_bytes(16, "big"))
            for span_no, parent_no, start_offset_ms, duration_ms in spans:
                span_id = _b64((trace_no * 100 + span_no).to_bytes(8, "big"))
                parent = _b64((trace_no * 100 + parent_no).to_bytes(8, "big")) if parent_no else ""
                start = BASE + dt.timedelta(milliseconds=start_offset_ms)
                end = start + dt.timedelta(milliseconds=duration_ms)
                rows.append(
                    f"('019e8759-0000-0000-{trace_no:04d}-{span_no:012d}', {cls.team.id}, '{trace_id}', "
                    f"'{span_id}', '{parent}', 'op-{span_no}', 2, "
                    f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', '{end.strftime('%Y-%m-%d %H:%M:%S.%f')}', "
                    f"'{start.strftime('%Y-%m-%d %H:%M:%S.%f')}', 0, 'web')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _trace_spans(self, trace_no: int) -> dict[str, dict]:
        trace_hex = trace_no.to_bytes(16, "big").hex()
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/trace/{trace_hex}/",
            {"dateRange": {"date_from": "2026-06-02T07:00:00Z", "date_to": "2026-06-02T09:00:00Z"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return {span["name"]: span for span in response.json()["results"]}

    def test_overlapping_children_cover_their_union_not_their_sum(self):
        spans = self._trace_spans(1)
        # Children 0-100ms and 50-150ms merge to 150ms covered → 850ms unaccounted in the root.
        self.assertEqual(spans["op-1"]["self_time_nano"], 850 * MS)

    def test_parallel_children_are_not_double_counted(self):
        spans = self._trace_spans(2)
        # Two children both spanning 0-100ms cover 100ms once → 900ms self-time.
        self.assertEqual(spans["op-1"]["self_time_nano"], 900 * MS)

    def test_leaf_self_time_is_its_own_duration(self):
        spans = self._trace_spans(1)
        self.assertEqual(spans["op-2"]["self_time_nano"], 100 * MS)
        self.assertEqual(spans["op-3"]["self_time_nano"], 100 * MS)
