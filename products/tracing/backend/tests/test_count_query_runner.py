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
        assert response.results == {"count": expected_count}

    def test_count_via_api_with_name_filter(self):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "filterGroup": [{"key": "name", "type": "span", "operator": "exact", "value": ROOT_NAME}],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/count/", body, format="json")
        assert res.status_code == 200, res.content
        # One root span named process_query_model per trace.
        assert res.json() == {"count": NUM_TRACES}
