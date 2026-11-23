import datetime as dt

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

MS = 1_000_000
T0800 = "2026-06-02T08:00:00+00:00"
SERVER, INTERNAL = 2, 1


class TestTraceSpansLatencyPercentiles(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        rows: list[str] = []

        def add(
            service: str,
            kind: int,
            duration_ms: int,
            parent: str = "",
            env: str = "",
            env_key: str = "deployment.environment",
        ) -> str:
            index = len(rows)
            span_id = _b64((5000 + index).to_bytes(8, "big"))
            start = dt.datetime(2026, 6, 2, 8, 0, 0)
            end = start + dt.timedelta(milliseconds=duration_ms)
            rows.append(
                f"('019e8758-0000-0000-0000-{index:012d}', {cls.team.id}, '{_b64(index.to_bytes(16, 'big'))}', "
                f"'{span_id}', '{parent}', 'op', {kind}, '{start:%Y-%m-%d %H:%M:%S.%f}', "
                f"'{end:%Y-%m-%d %H:%M:%S.%f}', '{start:%Y-%m-%d %H:%M:%S.%f}', 0, '{service}', "
                f"map('{env_key}', '{env}'))"
            )
            return span_id

        # web: server spans of 10ms..100ms, each with a slow internal child that must not count.
        for duration in range(10, 101, 10):
            parent = add("web", SERVER, duration)
            add("web", INTERNAL, 5_000, parent)
        # job: no server or consumer spans, so its root spans are its requests.
        for duration in (200, 400):
            add("job", INTERNAL, duration)
        # mixed: server spans in prod, only root spans in staging. Each environment picks its own population.
        add("mixed", SERVER, 100, env="prod")
        add("mixed", INTERNAL, 300, env="staging")
        add("clustered", SERVER, 100, env="cluster-a", env_key="k8s.cluster.name")
        add("clustered", INTERNAL, 300, env="cluster-b", env_key="k8s.cluster.name")

        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES "
            + ",".join(rows)
        )

    def _percentiles(self, service: str) -> list[dict]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/latency_percentiles/",
            {"query": {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, "serviceNames": [service]}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_percentiles_cover_entry_spans_only(self):
        rows = self._percentiles("web")
        bucket = next(row for row in rows if row["time"] == T0800)
        self.assertEqual(bucket["count"], 10)
        # Real quantiles over 10ms..100ms, not bucket edges, and the 5s children never pull them up.
        self.assertAlmostEqual(bucket["p50_ns"] / MS, 55, delta=1)
        self.assertGreater(bucket["p95_ns"] / MS, 90)
        self.assertLessEqual(bucket["p99_ns"] / MS, 100)

        empty = [row for row in rows if row["time"] != T0800]
        self.assertTrue(empty)
        self.assertTrue(all(row["count"] == 0 and row["p95_ns"] is None for row in empty))

    def test_service_without_entry_spans_falls_back_to_root_spans(self):
        bucket = next(row for row in self._percentiles("job") if row["time"] == T0800)
        self.assertEqual(bucket["count"], 2)
        self.assertAlmostEqual(bucket["p50_ns"] / MS, 300, delta=1)

    @parameterized.expand([("mixed",), ("clustered",)])
    def test_fallback_is_chosen_per_environment(self, service: str):
        bucket = next(row for row in self._percentiles(service) if row["time"] == T0800)
        self.assertEqual(bucket["count"], 2)
        self.assertGreater(bucket["p99_ns"] / MS, 250)
