import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes

from products.tracing.backend.facade.contracts import ServiceHealthParams
from products.tracing.backend.facade.enums import ServiceHealthCompare, ServiceHealthOrderBy, ServiceHealthSpanScope
from products.tracing.backend.tests.test_keyset_pagination import _TraceSpansTestBase

RUNNER_PATH = "products.tracing.backend.presentation.views.run_service_health_query"


def _url(team_id: int) -> str:
    return f"/api/projects/{team_id}/tracing/spans/service_health/"


class TestServiceHealthValidation(APIBaseTest):
    @parameterized.expand(
        [
            ("missing_query", {}),
            ("query_not_object", {"query": "x"}),
            ("unknown_compare", {"query": {"compare": "yesterday"}}),
            ("compare_object", {"query": {"compare": {"date_from": "-2d"}}}),
            ("baseline_not_object", {"query": {}, "baselineDateRange": "-2d"}),
            ("compare_wrong_type", {"query": {"compare": 3}}),
            ("bad_span_scope", {"query": {"spanScope": "root"}}),
            ("bad_order_by", {"query": {"orderBy": "name"}}),
            ("reversed_baseline", {"query": {}, "baselineDateRange": {"date_from": "-1d", "date_to": "-2d"}}),
            ("future_window", {"query": {"dateRange": {"date_from": "2099-01-01T00:00:00Z"}}}),
            ("future_baseline", {"query": {}, "baselineDateRange": {"date_from": "2099-01-01T00:00:00Z"}}),
            ("limit_too_small", {"query": {"limit": 0}}),
            ("limit_too_large", {"query": {"limit": 1000}}),
            ("bad_date", {"query": {"dateRange": {"date_from": "yesterday-ish"}}}),
            ("date_range_not_object", {"query": {"dateRange": "-1h"}}),
            ("numeric_date", {"query": {"dateRange": {"date_from": 5}}}),
            ("huge_window", {"query": {"dateRange": {"date_from": "-999999999d"}}}),
            (
                "year_one",
                {"query": {"dateRange": {"date_from": "0001-01-03T00:00:00Z", "date_to": "0001-01-10T00:00:00Z"}}},
            ),
        ]
    )
    def test_rejects_bad_input(self, _name, body):
        with patch(RUNNER_PATH) as runner:
            response = self.client.post(_url(self.team.id), body, format="json")
        self.assertEqual(response.status_code, 400, response.content)
        runner.assert_not_called()

    def test_defaults(self):
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")) as runner:
            self.client.post(_url(self.team.id), {"query": {}}, format="json")
        params = runner.call_args.kwargs["params"]
        self.assertEqual(
            params,
            ServiceHealthParams(
                date_from="-1h",
                date_to=None,
                compare=ServiceHealthCompare.PREVIOUS_PERIOD,
                environment=None,
                service_names=(),
                span_scope=ServiceHealthSpanScope.ENTRY,
                order_by=ServiceHealthOrderBy.STATUS,
                limit=25,
            ),
        )

    def test_parses_every_field(self):
        body = {
            "query": {
                "dateRange": {"date_from": "-30m", "date_to": None},
                "environment": "production",
                "serviceNames": ["api"],
                "spanScope": "all",
                "orderBy": "p95",
                "limit": 5,
            },
            "baselineDateRange": {"date_from": "-2d", "date_to": "-1d"},
        }
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")) as runner:
            self.client.post(_url(self.team.id), body, format="json")
        params = runner.call_args.kwargs["params"]
        self.assertEqual(params.date_from, "-30M")
        self.assertEqual(params.compare, ServiceHealthCompare.CUSTOM)
        self.assertEqual((params.compare_date_from, params.compare_date_to), ("-2d", "-1d"))
        self.assertEqual(params.service_names, ("api",))
        self.assertEqual((params.span_scope, params.order_by, params.limit), ("all", "p95", 5))

    @parameterized.expand(["none", "previous_period", "previous_day", "previous_week"])
    def test_accepts_compare_names(self, compare):
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")) as runner:
            self.client.post(_url(self.team.id), {"query": {"compare": compare}}, format="json")
        self.assertEqual(runner.call_args.kwargs["params"].compare, compare)

    def test_byte_cap_returns_an_actionable_400(self):
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")):
            response = self.client.post(
                _url(self.team.id), {"query": {"dateRange": {"date_from": "-7d"}}}, format="json"
            )
        self.assertEqual(response.status_code, 400, response.content)
        detail = response.json()["detail"]
        self.assertIn("10 GB", detail)
        self.assertIn("serviceNames", detail)
        self.assertIn('{"date_from": "-84h"}', detail)

    def test_byte_cap_on_a_short_window_recommends_a_smaller_one(self):
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")):
            response = self.client.post(
                _url(self.team.id),
                {"query": {"dateRange": {"date_from": "-1h"}}, "baselineDateRange": {"date_from": "-3h"}},
                format="json",
            )
        detail = response.json()["detail"]
        self.assertIn('{"date_from": "-30m"}', detail)
        self.assertIn("baselineDateRange", detail)

    def test_byte_cap_on_a_one_minute_window_recommends_seconds(self):
        with patch(RUNNER_PATH, side_effect=CHQueryErrorTooManyBytes("too many bytes")):
            response = self.client.post(
                _url(self.team.id), {"query": {"dateRange": {"date_from": "-1m"}}}, format="json"
            )
        self.assertIn('{"date_from": "-30s"}', response.json()["detail"])


class TestServiceHealthResponse(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()
        rows: list[tuple] = []
        for i in range(120):
            for service, start, errors in (
                ("worker", dt.datetime(2026, 6, 2, 7, 0), 0),
                ("worker", dt.datetime(2026, 6, 2, 8, 0), 12),
            ):
                ts = start + dt.timedelta(seconds=30 * i)
                rows.append(
                    (
                        f"019e8810-0000-0000-0000-{len(rows):012d}",
                        cls.team.id,
                        f"trace-{len(rows)}",
                        f"span-{len(rows)}",
                        "",
                        "consume",
                        5,
                        ts,
                        ts + dt.timedelta(milliseconds=20),
                        ts,
                        2 if i < errors else 0,
                        service,
                        {},
                    )
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, timestamp, "
            "end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES",
            rows,
        )

    def _post(self, **query) -> dict:
        body = {
            "query": {"dateRange": {"date_from": "2026-06-02T08:00:00Z", "date_to": "2026-06-02T09:00:00Z"}, **query}
        }
        response = self.client.post(_url(self.team.id), body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_response_shape(self):
        data = self._post()
        self.assertEqual(set(data), {"window", "summary", "services", "next", "truncated", "notes"})
        self.assertEqual(
            data["window"],
            {
                "current": {"date_from": "2026-06-02T08:00:00Z", "date_to": "2026-06-02T09:00:00Z"},
                "baseline": {"date_from": "2026-06-02T07:00:00Z", "date_to": "2026-06-02T08:00:00Z"},
                "timezone": "UTC",
            },
        )
        self.assertEqual(data["summary"]["services"], 1)
        self.assertEqual(data["summary"]["regressed"], 1)
        [row] = data["services"]
        self.assertEqual(
            list(row),
            [
                "service",
                "status",
                "reason",
                "requests",
                "throughput_per_min",
                "error_count",
                "error_rate_pct",
                "error_rate_delta_pp",
                "p50_ms",
                "p95_ms",
                "p95_change_pct",
                "p99_ms",
                "baseline_requests",
                "last_seen",
            ],
        )
        self.assertEqual(row["service"], "worker")
        self.assertEqual(row["status"], "regressed")
        self.assertEqual(row["error_rate_pct"], 10.0)
        self.assertEqual(row["p95_ms"], 20.0)
        self.assertTrue(row["last_seen"].endswith("Z"))
        self.assertFalse(data["truncated"])
        self.assertEqual(data["next"][0]["tool"], "apm-spans-aggregate")
