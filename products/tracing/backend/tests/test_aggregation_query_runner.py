import datetime as dt
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import CompareFilter, DateRange, TraceSpansAggregationQuery

from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.aggregation_query_runner import TraceSpansAggregationQueryRunner
from products.tracing.backend.logic import run_aggregation_query, run_tree_query
from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# Child starts 40ms after its parent. In nanoseconds that's 40_000_000 — the unit the
# avg_start_offset_nano column claims to report.
CHILD_OFFSET_MS = 40
EXPECTED_OFFSET_NANO = CHILD_OFFSET_MS * 1_000_000

MS_TO_NANO = 1_000_000


class TestPaginationReachesTheCacheKey(BaseTest):
    @parameterized.expand([("limit", {"limit": 10}, {"limit": 20}), ("offset", {"offset": 0}, {"offset": 10})])
    def test_different_pages_give_different_cache_keys(self, _name, first, second):
        query = TraceSpansAggregationQuery(dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO))
        first_key = TraceSpansAggregationQueryRunner(query, self.team, **first).get_cache_key()
        second_key = TraceSpansAggregationQueryRunner(query, self.team, **second).get_cache_key()
        assert first_key != second_key


class TestCompareFanOutTimings(BaseTest):
    def test_each_window_gets_its_own_timings_and_both_are_merged_back(self):
        received: list[HogQLTimings] = []

        def fake_execute(**kwargs):
            timings = kwargs["timings"]
            received.append(timings)
            with timings.measure("execute"):
                pass
            return SimpleNamespace(results=[])

        query = TraceSpansAggregationQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO), compareFilter=CompareFilter(compare=True)
        )
        runner = TraceSpansAggregationQueryRunner(query, self.team)
        with patch("products.tracing.backend.aggregation_query_runner.execute_hogql_query", side_effect=fake_execute):
            runner.calculate()

        assert len({id(t) for t in received}) == 2
        assert runner.timings not in received
        assert {"./series_0/execute", "./series_1/execute"} <= runner.timings.timings.keys()


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


class TestTraceSpansAggregationGroupByEndpoint(_TraceSpansTestBase):
    SERVICE = "api"
    SERVER, CLIENT = 2, 3
    SPANS = [
        ("/users/1", SERVER, {"http.method": "GET", "http.route": "/users/{id}"}),
        ("/users/2", SERVER, {"http.request.method": "GET", "http.route": "/users/{id}"}),
        ("GET", SERVER, {"http.method": "GET", "http.route": "/orders"}),
        ("GET", SERVER, {"http.method": "GET", "http.route": "/items"}),
        ("GET /health", SERVER, {"http.method": "GET"}),
        ("RunActivity:sync", SERVER, {}),
        ("GET", CLIENT, {"http.method": "GET", "http.route": "/upstream"}),
    ]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_str = (base + dt.timedelta(milliseconds=10)).strftime("%Y-%m-%d %H:%M:%S.%f")
        rows: list[str] = []
        for i, (name, kind, attributes) in enumerate(cls.SPANS):
            attribute_map = "map(" + ", ".join(f"'{key}__str', '{value}'" for key, value in attributes.items()) + ")"
            rows.append(
                f"('019e8762-0000-0000-0000-{i:012d}', {cls.team.id}, '{_b64(i.to_bytes(16, 'big'))}', "
                f"'{_b64((100 + i).to_bytes(8, 'big'))}', '', '{name}', {kind}, '{ts_str}', '{end_str}', "
                f"'{ts_str}', 0, '{cls.SERVICE}', {attribute_map})"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str) VALUES "
            + ",".join(rows)
        )

    @parameterized.expand(
        [
            (
                "by_span_name",
                False,
                {("/users/1", 1), ("/users/2", 1), ("GET", 3), ("GET /health", 1), ("RunActivity:sync", 1)},
            ),
            (
                "by_endpoint",
                True,
                {("GET /users/{id}", 2), ("GET /orders", 1), ("GET /items", 1), ("GET /health", 1)},
            ),
        ]
    )
    def test_rows(self, _name, group_by_endpoint, expected):
        response = run_aggregation_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            group_by_endpoint=group_by_endpoint,
        )
        self.assertEqual({(row.name, row.count) for row in response.results}, expected)


class TestTraceSpansAggregationHealth(_TraceSpansTestBase):
    SERVICE = "api"
    # (name, hour inside the query window or its previous period, span count, error count)
    GROUPS = [
        ("GET /orders", 6, 100, 0),
        ("GET /orders", 8, 100, 10),
        ("GET /items", 6, 100, 0),
        ("GET /items", 8, 100, 0),
        ("GET /new", 8, 5, 0),
        # Ranks first in the baseline and last in the current window.
        ("GET /legacy", 6, 300, 0),
        ("GET /legacy", 8, 1, 0),
    ]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        values: list[str] = []
        for name, hour, count, errors in cls.GROUPS:
            for j in range(count):
                i = len(values)
                ts = dt.datetime(2026, 6, 2, hour, 0, 0) + dt.timedelta(seconds=j)
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
                end_str = (ts + dt.timedelta(milliseconds=10)).strftime("%Y-%m-%d %H:%M:%S.%f")
                status = 2 if j >= count - errors else 0
                values.append(
                    f"('019e8763-0000-0000-0000-{i:012d}', {cls.team.id}, '{_b64(i.to_bytes(16, 'big'))}', "
                    f"'{_b64((1000 + i).to_bytes(8, 'big'))}', '', '{name}', 2, '{ts_str}', '{end_str}', "
                    f"'{ts_str}', {status}, '{cls.SERVICE}')"
                )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(values)
        )

    def test_classifies_each_row_against_the_previous_period(self):
        response = run_aggregation_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            include_health=True,
        )
        statuses = {row.name: row.health_status for row in response.results}
        self.assertEqual(
            {name: statuses[name] for name in ("GET /orders", "GET /items", "GET /new")},
            {"GET /orders": "regressed", "GET /items": "ok", "GET /new": "new"},
        )
        self.assertIsNone(response.compare)

    def test_api_compare_rows_follow_the_visible_page(self):
        # The view over-fetches one row for has_more, so the baseline also holds the row it drops.
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/aggregate/",
            {
                "query": {
                    "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                    "compareFilter": {"compare": True},
                    "includeHealth": True,
                    "limit": 1,
                    "offset": 2,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual([row["name"] for row in data["results"]], ["GET /new"])
        self.assertEqual(data["compare"], [])

    @parameterized.expand(
        [("previous_period", None, None), ("compare_filter", CompareFilter(compare=True), ["GET /legacy"])]
    )
    def test_a_paged_row_keeps_its_baseline(self, _name, compare_filter, expected_compare):
        response = run_aggregation_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            compare_filter=compare_filter,
            include_health=True,
            limit=1,
            offset=3,
        )
        self.assertEqual([row.name for row in response.results], ["GET /legacy"])
        self.assertNotEqual(response.results[0].health_status, "new")
        self.assertEqual(None if response.compare is None else [row.name for row in response.compare], expected_compare)
