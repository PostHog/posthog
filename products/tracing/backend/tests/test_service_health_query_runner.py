import datetime as dt

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.facade.contracts import ServiceHealthParams
from products.tracing.backend.facade.enums import (
    ServiceHealthCompare,
    ServiceHealthOrderBy,
    ServiceHealthSpanScope,
    ServiceHealthStatus,
)
from products.tracing.backend.service_health_query_runner import (
    MAX_REASON_LENGTH,
    ServiceHealthQueryRunner,
    ServiceWindowStats,
    aggregate_compare_filter,
    classify_service,
)
from products.tracing.backend.tests.test_keyset_pagination import _TraceSpansTestBase

CURRENT_FROM = dt.datetime(2026, 6, 2, 8, 0, 0)
CURRENT_TO = dt.datetime(2026, 6, 2, 9, 0, 0)
BASELINE_FROM = dt.datetime(2026, 6, 2, 7, 0, 0)
PREVIOUS_DAY_FROM = dt.datetime(2026, 6, 1, 8, 0, 0)

PRODUCTION = {"deployment.environment.name": "production"}


def _stats(
    requests: int,
    errors: int = 0,
    p95_ms: float = 10.0,
    last_seen: dt.datetime | None = None,
) -> ServiceWindowStats:
    return ServiceWindowStats(
        requests=requests,
        errors=errors,
        p50_ms=p95_ms,
        p95_ms=p95_ms,
        p99_ms=p95_ms,
        last_seen=last_seen or CURRENT_TO - dt.timedelta(seconds=20),
    )


class TestClassifyService(SimpleTestCase):
    @parameterized.expand(
        [
            ("ok", _stats(200), _stats(200), ServiceHealthStatus.OK),
            (
                "silent_no_current_spans",
                None,
                _stats(100, last_seen=CURRENT_FROM - dt.timedelta(minutes=10)),
                ServiceHealthStatus.SILENT,
            ),
            ("small_baseline_gone_is_not_silent", None, _stats(5), ServiceHealthStatus.OK),
            (
                "silent_spans_stopped_inside_window",
                _stats(300, last_seen=CURRENT_FROM + dt.timedelta(minutes=30)),
                _stats(300),
                ServiceHealthStatus.SILENT,
            ),
            ("new", _stats(50), None, ServiceHealthStatus.NEW),
            ("regressed_error_rate", _stats(200, errors=10), _stats(200, errors=1), ServiceHealthStatus.REGRESSED),
            ("regressed_p95", _stats(200, p95_ms=30.0), _stats(200, p95_ms=10.0), ServiceHealthStatus.REGRESSED),
            ("error_rise_below_ratio", _stats(200, errors=24), _stats(200, errors=20), ServiceHealthStatus.DEGRADED),
            ("regression_needs_volume", _stats(50, errors=10), _stats(50), ServiceHealthStatus.DEGRADED),
            ("degraded", _stats(200, errors=20), _stats(200, errors=20), ServiceHealthStatus.DEGRADED),
            ("recovered", _stats(200), _stats(200, errors=20), ServiceHealthStatus.RECOVERED),
            ("improved", _stats(200, p95_ms=10.0), _stats(200, p95_ms=40.0), ServiceHealthStatus.IMPROVED),
        ]
    )
    def test_status_rules(self, _name, current, baseline, expected):
        status, reason = classify_service(
            current=current, baseline=baseline, has_baseline=True, window_from=CURRENT_FROM, window_to=CURRENT_TO
        )
        self.assertEqual(status, expected, reason)
        self.assertLessEqual(len(reason), MAX_REASON_LENGTH)

    def test_regression_reason_names_the_rates(self):
        _, reason = classify_service(
            current=_stats(200, errors=10),
            baseline=_stats(200, errors=1),
            has_baseline=True,
            window_from=CURRENT_FROM,
            window_to=CURRENT_TO,
        )
        self.assertEqual(reason, "error rate 0.5% → 5.0%")

    def test_silent_reason_names_the_last_span(self):
        _, reason = classify_service(
            current=_stats(300, last_seen=dt.datetime(2026, 6, 2, 8, 30, 0)),
            baseline=None,
            has_baseline=False,
            window_from=CURRENT_FROM,
            window_to=CURRENT_TO,
        )
        self.assertTrue(reason.startswith("no spans since 08:30Z"), reason)

    def test_sparse_baseline_is_not_silent(self):
        status, _ = classify_service(
            current=None,
            baseline=_stats(30, last_seen=CURRENT_FROM - dt.timedelta(minutes=30)),
            has_baseline=True,
            window_from=CURRENT_FROM,
            window_to=CURRENT_TO,
            baseline_minutes=60,
        )
        self.assertNotEqual(status, ServiceHealthStatus.SILENT)

    def test_no_current_spans_is_not_silent_inside_the_gap(self):
        status, _ = classify_service(
            current=None,
            baseline=_stats(300, last_seen=CURRENT_TO - dt.timedelta(minutes=5)),
            has_baseline=True,
            window_from=CURRENT_TO - dt.timedelta(minutes=5),
            window_to=CURRENT_TO,
        )
        self.assertNotEqual(status, ServiceHealthStatus.SILENT)

    def test_without_a_baseline_only_absolute_rules_apply(self):
        status, _ = classify_service(
            current=_stats(200, errors=10),
            baseline=None,
            has_baseline=False,
            window_from=CURRENT_FROM,
            window_to=CURRENT_TO,
        )
        self.assertEqual(status, ServiceHealthStatus.DEGRADED)
        status, _ = classify_service(
            current=_stats(200), baseline=None, has_baseline=False, window_from=CURRENT_FROM, window_to=CURRENT_TO
        )
        self.assertEqual(status, ServiceHealthStatus.OK)


class TestAggregateCompareFilter(SimpleTestCase):
    @parameterized.expand(
        [
            (ServiceHealthCompare.PREVIOUS_PERIOD, {"compare": True}),
            (ServiceHealthCompare.PREVIOUS_DAY, {"compare": True, "compare_to": "-1d"}),
            (ServiceHealthCompare.PREVIOUS_WEEK, {"compare": True, "compare_to": "-7d"}),
            (ServiceHealthCompare.CUSTOM, None),
            (ServiceHealthCompare.NONE, None),
        ]
    )
    def test_maps_compare_to_the_aggregate_tool(self, compare, expected):
        self.assertEqual(aggregate_compare_filter(compare), expected)


class TestServiceHealthWindows(BaseTest):
    @parameterized.expand(
        [
            (ServiceHealthCompare.PREVIOUS_PERIOD, "2026-06-02T06:00:00Z", "2026-06-02T08:00:00Z"),
            (ServiceHealthCompare.PREVIOUS_DAY, "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z"),
            (ServiceHealthCompare.PREVIOUS_WEEK, "2026-05-26T08:00:00Z", "2026-05-26T10:00:00Z"),
        ]
    )
    @time_machine.travel("2026-06-02T10:00:00Z", tick=False)
    def test_baseline_window(self, compare, expected_from, expected_to):
        runner = ServiceHealthQueryRunner(team=self.team, params=ServiceHealthParams(date_from="-2h", compare=compare))
        window = runner.window()
        self.assertEqual(window["current"], {"date_from": "2026-06-02T08:00:00Z", "date_to": "2026-06-02T10:00:00Z"})
        self.assertEqual(window["baseline"], {"date_from": expected_from, "date_to": expected_to})
        self.assertEqual(window["timezone"], "UTC")

    def test_custom_baseline_window(self):
        params = ServiceHealthParams(
            date_from="2026-06-02T08:00:00Z",
            date_to="2026-06-02T09:00:00Z",
            compare=ServiceHealthCompare.CUSTOM,
            compare_date_from="2026-05-30T00:00:00Z",
            compare_date_to="2026-05-30T06:00:00Z",
        )
        window = ServiceHealthQueryRunner(team=self.team, params=params).window()
        self.assertEqual(window["baseline"], {"date_from": "2026-05-30T00:00:00Z", "date_to": "2026-05-30T06:00:00Z"})

    def test_no_baseline(self):
        params = ServiceHealthParams(date_from="-1h", compare=ServiceHealthCompare.NONE)
        self.assertIsNone(ServiceHealthQueryRunner(team=self.team, params=params).window()["baseline"])


def _spread(start: dt.datetime, count: int, minutes: int = 60) -> list[dt.datetime]:
    step = dt.timedelta(seconds=minutes * 60 / count)
    return [start + step * i for i in range(count)]


class TestServiceHealthQueryRunner(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()
        rows: list[tuple] = []

        def add(
            service: str,
            start: dt.datetime,
            count: int,
            *,
            errors: int = 0,
            duration_ms: float = 10.0,
            name: str = "GET /",
            kind: int = 2,
            parent: str = "",
            resource: dict | None = None,
            minutes: int = 60,
        ) -> None:
            for i, ts in enumerate(_spread(start, count, minutes)):
                index = len(rows)
                rows.append(
                    (
                        f"019e8800-0000-0000-0000-{index:012d}",
                        cls.team.id,
                        f"trace-{index}",
                        f"span-{index}",
                        parent,
                        name,
                        kind,
                        ts,
                        ts + dt.timedelta(milliseconds=duration_ms),
                        ts,
                        2 if i < errors else 0,
                        service,
                        PRODUCTION if resource is None else resource,
                    )
                )

        add("api", BASELINE_FROM, 200)
        add("api", CURRENT_FROM, 200)
        add("api", CURRENT_FROM, 200, errors=200, kind=1, parent="cGFyZW50", name="db query")
        add("api", CURRENT_FROM, 40, resource={"deployment.environment": "staging"})
        add("stage-svc", CURRENT_FROM, 30, resource={"env": "staging"})
        add("worker", BASELINE_FROM, 200, errors=1, kind=5, parent="cGFyZW50", name="consume order")
        add("worker", CURRENT_FROM, 150, errors=10, kind=5, parent="cGFyZW50", name="consume order")
        add("worker", CURRENT_FROM, 50, errors=2, kind=5, parent="cGFyZW50", name="consume refund")
        add("dispatch", BASELINE_FROM, 100)
        add("billing", CURRENT_FROM, 50)
        add("search", BASELINE_FROM, 200, duration_ms=10.0)
        add("search", CURRENT_FROM, 200, duration_ms=30.0)
        add("mailer", BASELINE_FROM, 200, errors=20)
        add("mailer", CURRENT_FROM, 200, errors=20)
        add("ledger", BASELINE_FROM, 200, errors=20)
        add("ledger", CURRENT_FROM, 200)
        add("cache", BASELINE_FROM, 200, duration_ms=40.0)
        add("cache", CURRENT_FROM, 200, duration_ms=10.0)
        add("cron", BASELINE_FROM, 150)
        add("cron", CURRENT_FROM, 150, minutes=30)
        add("nightly", PREVIOUS_DAY_FROM, 100)

        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, timestamp, "
            "end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES",
            rows,
        )

    def _run(self, **overrides):
        fields = {"date_from": "2026-06-02T08:00:00Z", "date_to": "2026-06-02T09:00:00Z", "environment": "production"}
        params = ServiceHealthParams(**{**fields, **overrides})
        return ServiceHealthQueryRunner(team=self.team, params=params).run()

    def _by_service(self, result) -> dict:
        return {row["service"]: row for row in result["services"]}

    def test_window_is_echoed_in_utc(self):
        result = self._run()
        self.assertEqual(result["window"]["current"]["date_from"], "2026-06-02T08:00:00Z")
        self.assertEqual(result["window"]["current"]["date_to"], "2026-06-02T09:00:00Z")
        self.assertEqual(result["window"]["baseline"]["date_from"], "2026-06-02T07:00:00Z")
        self.assertEqual(result["window"]["baseline"]["date_to"], "2026-06-02T08:00:00Z")

    def test_each_status(self):
        rows = self._by_service(self._run(limit=100))
        self.assertEqual(
            {service: row["status"] for service, row in rows.items()},
            {
                "api": ServiceHealthStatus.OK,
                "worker": ServiceHealthStatus.REGRESSED,
                "dispatch": ServiceHealthStatus.SILENT,
                "billing": ServiceHealthStatus.NEW,
                "search": ServiceHealthStatus.REGRESSED,
                "mailer": ServiceHealthStatus.DEGRADED,
                "ledger": ServiceHealthStatus.RECOVERED,
                "cache": ServiceHealthStatus.IMPROVED,
                "cron": ServiceHealthStatus.SILENT,
            },
        )

    def test_row_metrics_use_units(self):
        worker = self._by_service(self._run())["worker"]
        self.assertEqual(worker["requests"], 200)
        self.assertEqual(worker["error_count"], 12)
        self.assertEqual(worker["error_rate_pct"], 6.0)
        self.assertEqual(worker["error_rate_delta_pp"], 5.5)
        self.assertEqual(worker["baseline_requests"], 200)
        self.assertEqual(worker["throughput_per_min"], 3.3)
        self.assertEqual(worker["p95_ms"], 10.0)
        self.assertEqual(worker["p95_change_pct"], 0.0)
        self.assertEqual(worker["reason"], "error rate 0.5% → 6.0%")

        search = self._by_service(self._run())["search"]
        self.assertEqual((search["p50_ms"], search["p95_ms"], search["p99_ms"]), (30.0, 30.0, 30.0))
        self.assertEqual(search["p95_change_pct"], 200.0)

    def test_silent_row_has_no_current_metrics(self):
        dispatch = self._by_service(self._run())["dispatch"]
        self.assertEqual(dispatch["requests"], 0)
        self.assertEqual(dispatch["baseline_requests"], 100)
        self.assertIsNone(dispatch["error_rate_pct"])
        self.assertIsNone(dispatch["p95_ms"])
        self.assertTrue(dispatch["reason"].startswith("no spans since 07:"), dispatch["reason"])

    def test_entry_scope_skips_internal_spans(self):
        entry = self._by_service(self._run())["api"]
        all_spans = self._by_service(self._run(span_scope=ServiceHealthSpanScope.ALL))["api"]
        self.assertEqual((entry["requests"], entry["error_count"]), (200, 0))
        self.assertEqual((all_spans["requests"], all_spans["error_count"]), (400, 200))
        self.assertEqual(all_spans["status"], ServiceHealthStatus.REGRESSED)

    def test_environment_uses_the_fallback_chain(self):
        rows = self._by_service(self._run(environment="Staging"))
        self.assertEqual(set(rows), {"api", "stage-svc"})
        self.assertEqual(rows["api"]["requests"], 40)
        self.assertEqual(rows["stage-svc"]["requests"], 30)

    def test_no_environment_counts_every_label(self):
        params = ServiceHealthParams(date_from="2026-06-02T08:00:00Z", date_to="2026-06-02T09:00:00Z")
        rows = self._by_service(ServiceHealthQueryRunner(team=self.team, params=params).run())
        self.assertEqual(rows["api"]["requests"], 240)

    def test_service_names_filter(self):
        result = self._run(service_names=("worker", "dispatch"))
        self.assertEqual({row["service"] for row in result["services"]}, {"worker", "dispatch"})

    def test_previous_day_compare(self):
        rows = self._by_service(self._run(compare=ServiceHealthCompare.PREVIOUS_DAY, limit=100))
        self.assertEqual(rows["nightly"]["status"], ServiceHealthStatus.SILENT)
        self.assertEqual(rows["api"]["status"], ServiceHealthStatus.NEW)

    def test_custom_compare(self):
        rows = self._by_service(
            self._run(
                compare=ServiceHealthCompare.CUSTOM,
                compare_date_from="2026-06-01T08:00:00Z",
                compare_date_to="2026-06-01T09:00:00Z",
                limit=100,
            )
        )
        self.assertEqual(rows["nightly"]["status"], ServiceHealthStatus.SILENT)

    def test_no_compare(self):
        result = self._run(compare=ServiceHealthCompare.NONE, limit=100)
        rows = self._by_service(result)
        self.assertNotIn("dispatch", rows)
        self.assertEqual(rows["billing"]["status"], ServiceHealthStatus.OK)
        self.assertIsNone(rows["worker"]["error_rate_delta_pp"])
        self.assertIsNone(result["window"]["baseline"])
        self.assertTrue(any("compare" in note for note in result["notes"]))

    def test_order_by_status_puts_the_worst_first(self):
        statuses = [row["status"] for row in self._run(limit=100)["services"]]
        self.assertEqual(statuses[:4], [ServiceHealthStatus.SILENT] * 2 + [ServiceHealthStatus.REGRESSED] * 2)
        self.assertEqual(statuses[-1], ServiceHealthStatus.OK)

    @parameterized.expand(
        [
            (ServiceHealthOrderBy.ERROR_RATE, "mailer"),
            (ServiceHealthOrderBy.ERROR_COUNT, "mailer"),
            (ServiceHealthOrderBy.P95, "search"),
        ]
    )
    def test_order_by_metric(self, order_by, expected_first):
        self.assertEqual(self._run(order_by=order_by, limit=100)["services"][0]["service"], expected_first)

    def test_order_by_throughput(self):
        rows = self._run(order_by=ServiceHealthOrderBy.THROUGHPUT, limit=100)["services"]
        requests = [row["requests"] for row in rows]
        self.assertEqual(requests, sorted(requests, reverse=True))

    def test_limit_truncates_and_summary_counts_everything(self):
        result = self._run(limit=2)
        self.assertEqual(len(result["services"]), 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["summary"]["services"], 9)
        self.assertEqual(result["summary"]["silent"], 2)
        self.assertEqual(result["summary"]["regressed"], 2)
        self.assertEqual(result["summary"]["degraded"], 1)
        self.assertEqual(result["summary"]["new"], 1)

    def test_next_points_at_the_drill_down(self):
        result = self._run(environment=None)
        calls = {call["tool"]: call for call in result["next"]}
        self.assertEqual(set(calls), {"apm-spans-aggregate", "query-apm-spans"})
        aggregate = calls["apm-spans-aggregate"]
        self.assertEqual(aggregate["query"]["serviceNames"], ["search", "worker", "mailer"])
        self.assertEqual(
            aggregate["query"]["dateRange"], {"date_from": "2026-06-02T08:00:00Z", "date_to": "2026-06-02T09:00:00Z"}
        )
        self.assertEqual(aggregate["query"]["compareFilter"], {"compare": True})
        error_spans = calls["query-apm-spans"]["query"]
        self.assertEqual((error_spans["serviceNames"], error_spans["statusCodes"]), (["worker"], [2]))
        self.assertEqual((error_spans["flatSpans"], error_spans["rootSpans"]), (True, False))
        for call in result["next"]:
            self.assertLessEqual(len(call["why"]), MAX_REASON_LENGTH)
        self.assertEqual(self._run()["next"], [])

    def test_a_truncated_scan_does_not_invent_silent_or_new_services(self):
        with patch("products.tracing.backend.service_health_query_runner.SERVICE_SCAN_LIMIT", 3):
            result = self._run()
        statuses = {row["status"] for row in result["services"]}
        self.assertFalse(statuses & {ServiceHealthStatus.SILENT, ServiceHealthStatus.NEW}, statuses)
        self.assertTrue(result["truncated"])

    def test_runs_with_fail_fast_settings(self):
        with patch(
            "products.tracing.backend.service_health_query_runner.execute_hogql_query",
            side_effect=lambda **kwargs: type("R", (), {"results": []})(),
        ) as execute:
            self._run()
        settings = execute.call_args.kwargs["settings"]
        self.assertEqual(settings.max_execution_time, 30)
        self.assertEqual(settings.max_bytes_to_read, 10_000_000_000)
        self.assertEqual(settings.read_overflow_mode, "throw")
