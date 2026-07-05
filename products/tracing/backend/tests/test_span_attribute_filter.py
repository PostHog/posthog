import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"

# Span A carries the OTel code.* source-location attributes; span B has none of them.
WITH_CODE = "posthog-feature-flags"
WITHOUT_CODE = "other-service"
FILEPATH = "feature-flags/src/flags/flag_matching.rs"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestSpanAttributeFilter(ClickhouseTestMixin, APIBaseTest):
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
        # Keys in attributes_map_str carry a 5-char type suffix (__str); the `attributes` ALIAS strips it.
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES "
            "("
            f"'019e8754-0000-0000-0000-000000000001', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
            f"'{_b64((1).to_bytes(8, 'big'))}', '', 'root.with_code', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, "
            f"'{WITH_CODE}', "
            "map('code.filepath__str', '" + FILEPATH + "', 'code.namespace__str', 'flags', "
            "'code.lineno__str', '42', 'cache.hit__str', 'true'), "
            "map('service.version', '1.2.3')),"
            "("
            f"'019e8754-0000-0000-0000-000000000002', {cls.team.id}, '{_b64((2).to_bytes(16, 'big'))}', "
            f"'{_b64((2).to_bytes(8, 'big'))}', '', 'root.without_code', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, "
            f"'{WITHOUT_CODE}', "
            # http.status is stored as a NON-numeric string; req.tag is non-numeric. These guard the
            # "numeric-looking filter value silently routes to the float map" regression.
            "map('http.method__str', 'GET', 'http.status__str', '500ok', 'req.tag__str', 'v2'), "
            "map('service.version', '1.2.3'))"
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _query_services(self, prop: dict, root_spans: bool = False) -> list[str]:
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "rootSpans": root_spans,
                "filterGroup": [prop],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/query/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        return sorted(row["service_name"] for row in res.json()["results"])

    @parameterized.expand(
        [
            # Value-bearing operators already worked; value-less operators used to 500 (bare key -> illegal
            # JSON read on the Map column). All five must return 200 with the right spans.
            (
                "exact",
                {"key": "code.filepath", "type": "span_attribute", "operator": "exact", "value": FILEPATH},
                [WITH_CODE],
            ),
            (
                "icontains",
                {
                    "key": "code.filepath",
                    "type": "span_attribute",
                    "operator": "icontains",
                    "value": "flag_matching.rs",
                },
                [WITH_CODE],
            ),
            (
                "is_not",
                {"key": "code.filepath", "type": "span_attribute", "operator": "is_not", "value": "nope.rs"},
                sorted([WITH_CODE, WITHOUT_CODE]),
            ),
            ("is_set", {"key": "code.filepath", "type": "span_attribute", "operator": "is_set"}, [WITH_CODE]),
            (
                "is_not_set",
                {"key": "code.filepath", "type": "span_attribute", "operator": "is_not_set"},
                [WITHOUT_CODE],
            ),
            # code.namespace — a second standard code.* key.
            (
                "namespace_icontains",
                {"key": "code.namespace", "type": "span_attribute", "operator": "icontains", "value": "flag"},
                [WITH_CODE],
            ),
            (
                "namespace_is_set",
                {"key": "code.namespace", "type": "span_attribute", "operator": "is_set"},
                [WITH_CODE],
            ),
            # Equality on a numeric attribute uses the universal str map (string ops don't need __float).
            (
                "lineno_exact",
                {"key": "code.lineno", "type": "span_attribute", "operator": "exact", "value": "42"},
                [WITH_CODE],
            ),
            # Regression: a numeric-looking value with a string operator must NOT route to the float map,
            # which would silently drop the non-numeric stored value '500ok'.
            (
                "numeric_value_icontains_on_string_attr",
                {"key": "http.status", "type": "span_attribute", "operator": "icontains", "value": "50"},
                [WITHOUT_CODE],
            ),
            (
                "numeric_value_exact_on_string_attr",
                {"key": "http.status", "type": "span_attribute", "operator": "exact", "value": "500ok"},
                [WITHOUT_CODE],
            ),
            (
                "digit_icontains_on_alnum_attr",
                {"key": "req.tag", "type": "span_attribute", "operator": "icontains", "value": "2"},
                [WITHOUT_CODE],
            ),
            # Regression: a boolean filter value must resolve against the str map (where booleans are
            # stored as 'true'/'false'), not 500 by comparing the Float64 map to a string.
            (
                "bool_value_exact",
                {"key": "cache.hit", "type": "span_attribute", "operator": "exact", "value": True},
                [WITH_CODE],
            ),
            # Numeric comparison operators DO need the float map for correct ordering.
            (
                "lineno_gt_matches",
                {"key": "code.lineno", "type": "span_attribute", "operator": "gt", "value": "40"},
                [WITH_CODE],
            ),
            (
                "lineno_gt_excludes",
                {"key": "code.lineno", "type": "span_attribute", "operator": "gt", "value": "50"},
                [],
            ),
            # between/not_between are routed to the float map (both bounds numeric) — confirm the
            # two-element list value and float-map suffix resolve correctly.
            (
                "lineno_between_matches",
                {"key": "code.lineno", "type": "span_attribute", "operator": "between", "value": ["40", "50"]},
                [WITH_CODE],
            ),
            (
                "lineno_between_excludes",
                {"key": "code.lineno", "type": "span_attribute", "operator": "between", "value": ["50", "60"]},
                [],
            ),
            (
                "lineno_not_between_matches",
                {"key": "code.lineno", "type": "span_attribute", "operator": "not_between", "value": ["0", "41"]},
                [WITH_CODE],
            ),
        ]
    )
    def test_query_span_attribute_filters(self, _name, prop, expected_services):
        self.assertEqual(self._query_services(prop), expected_services)

    @parameterized.expand(
        [
            # Regression: filtering by an attribute while excludeAttributes=True used to 500. The
            # excluded projection is `map() AS attributes`, whose alias shadowed the `attributes` Map
            # table field the filter resolves against, so the filter's map access bound to the empty
            # map() and get_child blew up ("Cannot access property ... on 'attributes'"). Covers the
            # grouped (window-function) and flat span paths, and both the span and resource maps.
            (
                "span_attr_grouped",
                {"key": "code.filepath", "type": "span_attribute", "operator": "is_set"},
                False,
                [WITH_CODE],
            ),
            (
                "span_attr_flat",
                {"key": "code.filepath", "type": "span_attribute", "operator": "is_set"},
                True,
                [WITH_CODE],
            ),
            (
                "resource_attr_grouped",
                {"key": "service.version", "type": "span_resource_attribute", "operator": "exact", "value": "1.2.3"},
                False,
                sorted([WITH_CODE, WITHOUT_CODE]),
            ),
        ]
    )
    def test_attribute_filter_with_exclude_attributes(self, _name, prop, flat_spans, expected_services):
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "excludeAttributes": True,
                "flatSpans": flat_spans,
                "filterGroup": [prop],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/query/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(sorted(row["service_name"] for row in res.json()["results"]), expected_services)

    def test_span_attribute_filter_composes_with_root_spans_flag(self):
        # rootSpans=True (the query endpoint's default) ANDs `is_root_span = 1` onto the attribute
        # filter (commit #61397). Both test spans are roots, so an attribute filter still narrows
        # correctly in either mode — i.e. our suffix fix and the root-span gating compose cleanly.
        prop = {"key": "code.filepath", "type": "span_attribute", "operator": "is_set"}
        self.assertEqual(self._query_services(prop, root_spans=True), [WITH_CODE])
        self.assertEqual(self._query_services(prop, root_spans=False), [WITH_CODE])

    def _count(self, prop: dict) -> int:
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "filterGroup": [prop],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/count/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["count"]

    @parameterized.expand(
        [
            # The aggregation runner (count/sparkline/histogram/tree) shared the same value-less bug.
            ("is_set", {"key": "code.filepath", "type": "span_attribute", "operator": "is_set"}, 1),
            ("is_not_set", {"key": "code.filepath", "type": "span_attribute", "operator": "is_not_set"}, 1),
            (
                "icontains",
                {
                    "key": "code.filepath",
                    "type": "span_attribute",
                    "operator": "icontains",
                    "value": "flag_matching.rs",
                },
                1,
            ),
        ]
    )
    def test_count_span_attribute_filters(self, _name, prop, expected_count):
        self.assertEqual(self._count(prop), expected_count)

    def test_invalid_operator_returns_400_not_500(self):
        # A genuinely malformed filter is rejected at model validation with a clean 400, never a bare 500.
        body = {
            "query": {
                "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                "rootSpans": False,
                "filterGroup": [
                    {"key": "code.filepath", "type": "span_attribute", "operator": "not_a_real_operator", "value": "x"}
                ],
            }
        }
        res = self.client.post(f"/api/projects/{self.team.id}/tracing/spans/query/", body, format="json")
        self.assertEqual(res.status_code, 400, res.content)
