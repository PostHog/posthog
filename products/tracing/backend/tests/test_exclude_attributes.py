import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, TraceSpansQuery

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.logic import TraceSpansQueryRunner

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestExcludeAttributes(ClickhouseTestMixin, APIBaseTest):
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
        ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_str = (base + dt.timedelta(milliseconds=5)).strftime("%Y-%m-%d %H:%M:%S.%f")
        # `attributes` is an ALIAS over attributes_map_str whose keys carry a `__str` type suffix
        # that left(k, -5) strips — so 'http.method__str' surfaces as 'http.method'.
        # `resource_attributes` is a physical column, inserted as-is.
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES "
            "("
            f"'019e8754-0000-0000-0000-000000000001', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
            f"'{_b64((1).to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, 'web', "
            "map('http.method__str', 'POST'), map('service.version', '1.2.3', 'host.name', 'web-1'))"
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _run(self, *, exclude: bool) -> list[dict]:
        query = TraceSpansQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            orderBy="timestamp",
            limit=100,
            excludeAttributes=exclude,
        )
        return TraceSpansQueryRunner(query, self.team).run().results

    @parameterized.expand(
        [
            # excludeAttributes=False keeps both populated maps.
            ("included_by_default", False, {"http.method": "POST"}, {"service.version": "1.2.3", "host.name": "web-1"}),
            # excludeAttributes=True: keys stay present (positional mapping is stable) but the maps are empty.
            ("omitted_when_excluded", True, {}, {}),
        ]
    )
    def test_attributes(self, _name, exclude, expected_attributes, expected_resource_attributes):
        results = self._run(exclude=exclude)
        self.assertEqual(results[0]["attributes"], expected_attributes)
        self.assertEqual(results[0]["resource_attributes"], expected_resource_attributes)
        # Guards the positional-index shift from adding the resource column: the per-trace duration
        # key (the last SELECT column) must still land on the right value.
        self.assertEqual(results[0]["trace_duration"], 5_000_000)

    @parameterized.expand(
        [
            # excludeAttributes=True + an attribute filter in the WHERE used to 500: the excluded-map
            # placeholder was aliased `attributes` / `resource_attributes`, shadowing the physical
            # columns so the filter's `attributes.<key>` could no longer resolve. Both query builders
            # (whole-trace `flatSpans=False`, flat `flatSpans=True`) and both attribute kinds must
            # now return the matching row with the maps emptied.
            (
                "whole_trace_span_attr",
                False,
                {"key": "http.method", "type": "span_attribute", "operator": "exact", "value": "POST"},
            ),
            (
                "flat_span_attr",
                True,
                {"key": "http.method", "type": "span_attribute", "operator": "exact", "value": "POST"},
            ),
            (
                "whole_trace_resource_attr",
                False,
                {"key": "service.version", "type": "span_resource_attribute", "operator": "exact", "value": "1.2.3"},
            ),
            (
                "flat_resource_attr",
                True,
                {"key": "service.version", "type": "span_resource_attribute", "operator": "exact", "value": "1.2.3"},
            ),
        ]
    )
    def test_exclude_attributes_with_attribute_filter(self, _name, flat_spans, prop):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "rootSpans": False,
                "flatSpans": flat_spans,
                "excludeAttributes": True,
                "filterGroup": [prop],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/query/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        results = res.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["attributes"], {})
        self.assertEqual(results[0]["resource_attributes"], {})
