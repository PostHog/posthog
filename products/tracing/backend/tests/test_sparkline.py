import datetime as dt

from posthog.clickhouse.client import sync_execute

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

        rows: list[str] = []
        for i, (timestamp, service, status_code) in enumerate(SPANS):
            trace_id = _b64(i.to_bytes(16, "big"))
            span_id = _b64((1000 + i).to_bytes(8, "big"))
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(
                f"('019e8757-0000-0000-0000-{i:012d}', {cls.team.id}, '{trace_id}', '{span_id}', '', "
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
    ) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}}
        if service_names is not None:
            query["serviceNames"] = service_names
        if status_codes is not None:
            query["statusCodes"] = status_codes
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
