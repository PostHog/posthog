import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.count_query_runner import run_count_query

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"
NUM_TRACES = 3  # each trace = 1 root + 2 children = 3 spans → 9 spans total
ROOT_NAME = "process_query_model"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestTraceSpansCount(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tag_queries(product="tracing", feature="query")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(
            "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
            "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
        )
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        base = dt.datetime(2026, 6, 2, 8, 0, 0)

        def _row(uuid_suffix: int, trace_id: str, span_id: str, parent: str, name: str, ts_str: str) -> str:
            return (
                "("
                f"'019e8754-0000-0000-0000-{uuid_suffix:012d}', {cls.team.id}, '{trace_id}', "
                f"'{span_id}', '{parent}', '{name}', 2, '{ts_str}', '{ts_str}', '{ts_str}', 0, 'web'"
                ")"
            )

        rows = []
        for t in range(NUM_TRACES):
            trace_id = _b64((t + 1).to_bytes(16, "big"))
            root_span_id = _b64((t * 10 + 1).to_bytes(8, "big"))
            ts_str = (base + dt.timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S.%f")
            rows.append(_row(t * 10 + 1, trace_id, root_span_id, "", ROOT_NAME, ts_str))
            rows.append(
                _row(t * 10 + 2, trace_id, _b64((t * 10 + 2).to_bytes(8, "big")), root_span_id, "child.a", ts_str)
            )
            rows.append(
                _row(t * 10 + 3, trace_id, _b64((t * 10 + 3).to_bytes(8, "big")), root_span_id, "child.b", ts_str)
            )

        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    @parameterized.expand(
        [
            # No service filter → every span in the window.
            ("unfiltered_returns_all_spans", None, NUM_TRACES * 3),
            # A service that emitted nothing → zero.
            ("no_match_returns_zero", ["does-not-exist"], 0),
        ]
    )
    def test_count(self, _name, service_names, expected_count):
        response = run_count_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            service_names=service_names,
        )
        self.assertEqual(response.results["count"], expected_count)

    @parameterized.expand(
        [
            # count() is per-span; traceCount is distinct traces whose root matches. Unfiltered, every
            # root matches, so count = 9 spans but traceCount = 3 traces.
            ("unfiltered", None, NUM_TRACES * 3, NUM_TRACES),
            ("no_match_returns_zero_for_both", ["does-not-exist"], 0, 0),
        ]
    )
    def test_count_includes_distinct_trace_count(self, _name, service_names, expected_spans, expected_traces):
        response = run_count_query(
            team=self.team,
            date_range=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            service_names=service_names,
        )
        self.assertEqual(response.results, {"count": expected_spans, "traceCount": expected_traces})

    def test_count_via_api_with_name_filter(self):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "filterGroup": [{"key": "name", "type": "span", "operator": "exact", "value": ROOT_NAME}],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/count/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        # One root span named process_query_model per trace.
        self.assertEqual(res.json()["count"], NUM_TRACES)

    def test_count_api_child_only_filter_matches_spans_but_no_trace_roots(self):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "filterGroup": [{"key": "is_root_span", "type": "span", "operator": "exact", "value": False}],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/count/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        # 2 child spans per trace = 6 matching spans, but no trace's ROOT matches (the filter excludes
        # roots), so the Traces view shows 0 traces — traceCount must agree with that, not count traces
        # by any matching span.
        self.assertEqual(res.json(), {"count": NUM_TRACES * 2, "traceCount": 0})

    @parameterized.expand(
        [
            # Seed: 3 traces × (1 root + 2 children); every span is status_code=0 (Unset)
            # and kind=2 (Server). A span-field filter must RESTRICT the count, never
            # silently match every row — across the value forms agents actually send.
            ("is_root_span_bool_true_matches_roots", "is_root_span", True, NUM_TRACES),
            ("is_root_span_bool_false_matches_children", "is_root_span", False, NUM_TRACES * 2),
            ("is_root_span_string_true_matches_roots", "is_root_span", "true", NUM_TRACES),
            ("is_root_span_string_false_matches_children", "is_root_span", "false", NUM_TRACES * 2),
            ("is_root_span_int_one_matches_roots", "is_root_span", 1, NUM_TRACES),
            ("is_root_span_int_zero_matches_children", "is_root_span", 0, NUM_TRACES * 2),
            ("status_code_int_2_matches_no_errors", "status_code", 2, 0),
            ("status_code_str_2_matches_no_errors", "status_code", "2", 0),
            ("status_code_int_0_matches_all_unset", "status_code", 0, NUM_TRACES * 3),
            ("kind_str_3_matches_no_clients", "kind", "3", 0),
            ("kind_int_2_matches_all_servers", "kind", 2, NUM_TRACES * 3),
        ]
    )
    def test_count_span_field_filters_restrict(self, _name, key, value, expected_count):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "filterGroup": [{"key": key, "type": "span", "operator": "exact", "value": value}],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/count/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["count"], expected_count)
