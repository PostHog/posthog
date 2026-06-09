import os
import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    HogQLFilters,
    LogPropertyFilter,
    LogPropertyFilterType,
    LogsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models.utils import UUIDT

from products.logs.backend.logs_query_runner import LogsQueryRunner


class TestAttributeFilters(APIBaseTest):
    def test_log_attribute_filters(self):
        """Test that log attribute filters are properly converted and applied"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(
                                key="service.name",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_ATTRIBUTE,
                                value="web-server",
                            ),
                            LogPropertyFilter(
                                key="http.method",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_ATTRIBUTE,
                                value="POST",
                            ),
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # Verify that log attribute filters are included in the query
        self.assertIn("service.name", query_str)
        self.assertIn("http.method", query_str)
        # Log attributes DO NOT use resource_fingerprint filtering for optimization
        # this optimization was premature and needs more thought, and probably has very little benefit anyway
        self.assertNotIn("in(resource_fingerprint", query_str)

    def _attribute_filter_for(self, *, key, operator, value):
        """Build a single LogAttribute filter and return the LogsFilterBuilder's processed
        copy, whose `.key` carries the `__str` / `__float` suffix the routing logic chose."""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(
                                key=key,
                                operator=operator,
                                type=LogPropertyFilterType.LOG_ATTRIBUTE,
                                value=value,
                            )
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )
        af = LogsQueryRunner(query=query, team=self.team)._filter_builder.attribute_filters
        self.assertEqual(len(af), 1)
        return af[0]

    @parameterized.expand(
        [
            # Equality / identity operators on numeric-looking values MUST route to __str.
            ("exact_single_numeric", PropertyOperator.EXACT, "69339"),
            ("exact_numeric_list", PropertyOperator.EXACT, ["5", "8675309"]),
            ("is_not_numeric", PropertyOperator.IS_NOT, ["5"]),
            ("icontains_numeric", PropertyOperator.ICONTAINS, "500"),
        ]
    )
    def test_equality_operators_on_numeric_values_route_to_str(self, _name, operator, value):
        """Regression: numeric distinct_ids (e.g. `69339`) must be matched in the `__str`
        map, not `__float`. Routing equality to `__float` is the root cause of all-numeric
        distinct_ids failing to link logs to a person on the profile Logs tab."""
        f = self._attribute_filter_for(key="posthog.distinct_id", operator=operator, value=value)
        self.assertTrue(f.key.endswith("__str"), f"expected __str routing, got {f.key!r}")
        self.assertFalse(f.key.endswith("__float"))

    @parameterized.expand(
        [
            ("gt", PropertyOperator.GT),
            ("gte", PropertyOperator.GTE),
            ("lt", PropertyOperator.LT),
            ("lte", PropertyOperator.LTE),
        ]
    )
    def test_numeric_range_operators_still_route_to_float(self, _name, operator):
        """Numeric range comparisons keep `__float` routing — string ordering would be
        lexicographically wrong (`"100" < "99"`). This is what the fix deliberately preserves."""
        f = self._attribute_filter_for(key="duration_ms", operator=operator, value="500")
        self.assertTrue(f.key.endswith("__float"), f"expected __float routing, got {f.key!r}")

    def test_leading_zero_and_plain_numeric_do_not_collide(self):
        """`"007"` and `"7"` both parse as float 7.0, so under `__float` they would collide
        (one person's logs leaking onto another). Under `__str` they stay distinct, exact
        string values — verify both route to `__str` and keep their literal value."""
        f_007 = self._attribute_filter_for(key="posthog.distinct_id", operator=PropertyOperator.EXACT, value=["007"])
        f_7 = self._attribute_filter_for(key="posthog.distinct_id", operator=PropertyOperator.EXACT, value=["7"])
        self.assertTrue(f_007.key.endswith("__str"))
        self.assertTrue(f_7.key.endswith("__str"))
        self.assertEqual(f_007.value, ["007"])
        self.assertEqual(f_7.value, ["7"])

    def test_resource_attribute_filters(self):
        """Test that resource attribute filters are properly handled"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(
                                key="k8s.container.name",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="nginx",
                            ),
                            LogPropertyFilter(
                                key="k8s.pod.name",
                                operator=PropertyOperator.ICONTAINS,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="backend",
                            ),
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # Verify resource attribute filtering logic is applied
        self.assertIn("k8s.container.name", query_str)
        self.assertIn("k8s.pod.name", query_str)
        self.assertIn("in(resource_fingerprint", query_str)

    def test_negative_resource_attribute_filters(self):
        """Test that negative resource attribute filters work correctly"""

        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(
                                key="k8s.container.name",
                                operator=PropertyOperator.IS_NOT,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="nginx",
                            )
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # Verify negative filtering uses NOT IN subquery pattern
        self.assertIn("k8s.container.name", query_str)
        self.assertIn("notIn(resource_fingerprint", query_str)
        self.assertNotIn("in(resource_fingerprint", query_str)

    def test_mixed_attribute_filters(self):
        """Test combinations of log attributes and resource attributes"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            # Log attribute
                            LogPropertyFilter(
                                key="http.status_code",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_ATTRIBUTE,
                                value="500",
                            ),
                            # Resource attribute
                            LogPropertyFilter(
                                key="service.name",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="api-server",
                            ),
                            # Regular log filter
                            LogPropertyFilter(
                                key="message",
                                operator=PropertyOperator.ICONTAINS,
                                type=LogPropertyFilterType.LOG,
                                value="error",
                            ),
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # All filter types should be present. `http.status_code` uses Exact (equality),
        # so it routes to the `__str` map — equality/identity matching never uses `__float`
        # (that's reserved for numeric range comparisons). See test_*_routes_to_str/float below.
        self.assertIn("http.status_code__str", query_str)
        self.assertIn("service.name", query_str)
        self.assertIn("message", query_str)
        self.assertNotIn("service.name__str", query_str)
        self.assertNotIn("message__str", query_str)
        self.assertIn("in(resource_fingerprint", query_str)

    def test_positive_and_negative_resource_attribute_filters(self):
        """Test combinations of log attributes and resource attributes"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            # positive resource attribute
                            LogPropertyFilter(
                                key="service.name",
                                operator=PropertyOperator.EXACT,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="api-server",
                            ),
                            # negative resource attribute
                            LogPropertyFilter(
                                key="service.namespace",
                                operator=PropertyOperator.IS_NOT,
                                type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                                value="posthog",
                            ),
                        ],
                    )
                ],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # All filter types should be present
        self.assertIn("service.name", query_str)
        self.assertIn("service.namespace", query_str)
        self.assertIn("notIn(resource_fingerprint", query_str)
        self.assertIn("in(resource_fingerprint", query_str)

    def test_resource_fingerprint_filter(self):
        """Test that resourceFingerprint parameter adds a direct equality filter"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[],
                    )
                ],
            ),
            resourceFingerprint="12345678",
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        # Verify resource_fingerprint equality filter is present
        self.assertIn("resource_fingerprint", query_str)
        self.assertIn("12345678", query_str)

    def test_search_term_filter(self):
        """Test that searchTerm adds a body ILIKE filter"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            searchTerm="timeout error",
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        self.assertIn("body", query_str)
        self.assertIn("timeout error", query_str)
        self.assertIn("indexHint", query_str)

    def test_no_search_term_filter(self):
        """Test that omitting searchTerm does not add a body filter"""
        query = LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            ),
            kind="LogsQuery",
        )

        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        query_str = executor.clickhouse_prepared_ast.to_hogql()

        self.assertNotIn("ilike(body", query_str.lower())


class TestLogsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def _make_logs_api_request(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/query", data={"query": query_params})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @freeze_time("2025-12-16T10:33:00Z")
    def test_logs_integration_exact_limit(self):
        # query matches exactly 50 results from the test data
        query_params = {
            "dateRange": {"date_from": "2025-12-16T10:32:36.184820Z", "date_to": None},
            "limit": 50,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 50)
        self.assertFalse(response["hasMore"])
        self.assertEqual(len(queries), 1)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_logs_integration_one_more(self):
        # query matches exactly 51 results from the test data
        query_params = {
            "dateRange": {"date_from": "2025-12-16 10:32:36.178572Z", "date_to": None},
            "limit": 50,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 50)
        self.assertTrue(response["hasMore"])
        self.assertEqual(len(queries), 1)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_logs_slicing(self):
        # should slice the query, only return 100 results first time, then get the rest
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:32:36.178572Z", "date_to": None},
            "limit": 101,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 101)
        self.assertEqual(len(queries), 2)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_resource_filters(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:32:36.178572Z", "date_to": None},
            "limit": 10,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "k8s.pod.name",
                                "value": "efs-csi-node",
                                "operator": "icontains",
                                "type": "log_resource_attribute",
                            },
                            {
                                "key": "k8s.pod.name",
                                "value": ["efs-csi-node-pbnbw"],
                                "operator": "exact",
                                "type": "log_resource_attribute",
                            },
                            {"key": "logtag", "value": ["F"], "operator": "exact", "type": "log_attribute"},
                        ],
                    }
                ],
            },
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(len(queries), 2)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_resource_negative_filters(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:32:36.178572Z", "date_to": None},
            "limit": 10,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "k8s.pod.name",
                                "value": "efs-csi-node",
                                "operator": "icontains",
                                "type": "log_resource_attribute",
                            },
                            {
                                "key": "k8s.pod.name",
                                "value": ["efs-csi-node-pbnbw"],
                                "operator": "exact",
                                "type": "log_resource_attribute",
                            },
                            {"key": "logtag", "value": ["F"], "operator": "is_not", "type": "log_attribute"},
                        ],
                    }
                ],
            },
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 0)
        self.assertEqual(len(queries), 2)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_multiple_negative_resource_attribute_filters(self):
        # Two negative resource attribute filters on disjoint values (no log has both an envoy
        # container AND the kube-system namespace). The fix exists so a resource is excluded when
        # it matches ANY of the negative filters, not just when it matches every one. Pre-fix this
        # would return ~all logs because nothing matched both filters at once.
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:00:36.178572Z", "date_to": None},
            "limit": 2000,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "k8s.container.name",
                                "value": "envoy",
                                "operator": "is_not",
                                "type": "log_resource_attribute",
                            },
                            {
                                "key": "k8s.namespace.name",
                                "value": "kube-system",
                                "operator": "is_not",
                                "type": "log_resource_attribute",
                            },
                        ],
                    }
                ],
            },
        }

        response = self._make_logs_api_request(query_params)
        results = response["results"]

        # at least some logs come back (sanity check)
        self.assertGreater(len(results), 0)
        # neither excluded value appears anywhere — proves OR semantics
        for result in results:
            self.assertNotEqual(result["resource_attributes"].get("k8s.container.name"), "envoy")
            self.assertNotEqual(result["resource_attributes"].get("k8s.namespace.name"), "kube-system")
        # both excluded groups exist in the test data, so the result count must be strictly less than
        # the unfiltered count. Pre-fix this would have returned every log in range (since no resource
        # matched both filters at once).
        unfiltered = self._make_logs_api_request(
            {
                "dateRange": query_params["dateRange"],
                "limit": query_params["limit"],
                "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            }
        )
        self.assertLess(len(results), len(unfiltered["results"]))

    @freeze_time("2025-12-16T10:33:00Z")
    def test_resource_negative_attribute_filters(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:00:36.178572Z", "date_to": None},
            "limit": 100,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "k8s.deployment.name",
                                "value": "argo-rollouts",
                                "operator": "icontains",
                                "type": "log_resource_attribute",
                            },
                            {
                                "key": "message",
                                "value": ["time=2025-12-16T09:04:40.952Z"],
                                "operator": "not_icontains",
                                "type": "log_attribute",
                            },
                        ],
                    }
                ],
            },
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 99)
        self.assertEqual(len(queries), 2)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_resource_number_filters(self):
        query_params = {
            "dateRange": {"date_from": "-2h", "date_to": "2025-12-16 09:10:36.178572Z"},
            "limit": 10,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "k8s.container.restart_count",
                                "value": "0",
                                "operator": "gt",
                                "type": "log_resource_attribute",
                            }
                        ],
                    }
                ],
            },
        }

        with self.capture_select_queries() as queries:
            response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 10)
        self.assertEqual(len(queries), 2)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_trace_and_span_ids_returned_as_hex(self):
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:01:22.139425Z", "date_to": "2025-12-16 09:01:22.139426Z"},
            "limit": 1,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        response = self._make_logs_api_request(query_params)
        self.assertEqual(len(response["results"]), 1)

        result = response["results"][0]
        # trace_id stored as base64 "ASNFZ4mrze8BI0VniavN7w==" should be returned as hex
        self.assertEqual(result["trace_id"], "0123456789ABCDEF0123456789ABCDEF")
        # span_id stored as base64 "/ty6mHZUMhA=" should be returned as hex
        self.assertEqual(result["span_id"], "FEDCBA9876543210")

    def test_logs_attributes_endpoint(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/logs/attributes",
            {
                "dateRange": '{"date_from": "2025-12-16T09:49:36.184820Z", "date_to": null}',
                "attribute_type": "log",
                "search": "x_forwarded_proto",
                "limit": "10",
                "offset": "0",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "x_forwarded_proto")
        self.assertEqual(data["results"][0]["propertyFilterType"], "log_attribute")

    def test_logs_values_endpoint(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/logs/values",
            {
                "dateRange": '{"date_from": "2025-12-16T10:32:36.184820Z", "date_to": null}',
                "key": "service.name",
                "search": "con",
                "attribute_type": "resource",
                "limit": "10",
                "offset": "0",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["results"][0]["name"], "cdp-legacy-events-consumer")

        response = self.client.get(
            f"/api/projects/{self.team.id}/logs/values",
            {
                "dateRange": '{"date_from": "2025-12-16T10:32:36.184820Z", "date_to": null}',
                "attribute_type": "log",
                "limit": "10",
                "offset": "0",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_resource_fingerprint_integration(self):
        """Integration test for resource fingerprint queries using actual test data"""
        # First, get logs with a specific resource attribute to identify a resource fingerprint
        query_params_initial = {
            "dateRange": {"date_from": "2025-12-16 09:01:00Z", "date_to": None},
            "limit": 10,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "type": "log_resource_attribute",
                                "key": "k8s.container.name",
                                "operator": "exact",
                                "value": ["argo-rollouts-dashboard"],
                            }
                        ],
                    }
                ],
            },
        }

        response_initial = self._make_logs_api_request(query_params_initial)
        self.assertGreater(len(response_initial["results"]), 0)

        # Get the resource fingerprint from the first result
        resource_fingerprint = response_initial["results"][0]["resource_fingerprint"]
        self.assertIsNotNone(resource_fingerprint)

        # Now test filtering by that specific resource fingerprint
        query_params_fingerprint = {
            "dateRange": {"date_from": "2025-12-16 09:01:00Z", "date_to": None},
            "limit": 50,
            "resourceFingerprint": resource_fingerprint,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

        with self.capture_select_queries():
            response_fingerprint = self._make_logs_api_request(query_params_fingerprint)

        # Verify that all results have the same resource fingerprint
        for result in response_fingerprint["results"]:
            self.assertEqual(result["resource_fingerprint"], resource_fingerprint)

        # Verify all results have the expected resource attributes
        for result in response_fingerprint["results"]:
            self.assertEqual(result["resource_attributes"]["k8s.container.name"], "argo-rollouts-dashboard")
            self.assertEqual(result["resource_attributes"]["service.name"], "argo-rollouts")

    # ── time_bucket day-boundary tests ──────────────────────────────────
    # These use the "boundary-test-svc" log lines appended to test_logs.jsonnd
    # spanning Dec 14-18 with edge cases around midnight.

    def _boundary_bodies(self, query_params):
        """Helper: run a logs query and return the set of body strings that start with 'boundary-log-'."""
        response = self._make_logs_api_request(query_params)
        return {r["body"] for r in response["results"] if r["body"].startswith("boundary-log-")}

    def _boundary_query(self, date_from, date_to=None, limit=100):
        return {
            "dateRange": {"date_from": date_from, "date_to": date_to},
            "limit": limit,
            "serviceNames": ["boundary-test-svc"],
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_single_day_no_boundary(self):
        """Query entirely within Dec 15 — should only return Dec 15 logs."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-15 00:00:00Z", "2025-12-16 00:00:00Z"))
        self.assertIn("boundary-log-dec15-morning", bodies)
        self.assertIn("boundary-log-dec15-2359", bodies)
        self.assertIn("boundary-log-dec15-2359-last-micro", bodies)
        # Dec 14 and Dec 16 logs must NOT appear
        self.assertNotIn("boundary-log-dec14-noon", bodies)
        self.assertNotIn("boundary-log-dec16-midnight-exact", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_cross_midnight_dec15_to_dec16(self):
        """Query spanning 23:59 Dec 15 → 00:01 Dec 16 crosses the day boundary."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-15 23:59:00Z", "2025-12-16 00:00:012Z"))
        # Late Dec 15 logs
        self.assertIn("boundary-log-dec15-2359", bodies)
        self.assertIn("boundary-log-dec15-2359-last-micro", bodies)
        # Early Dec 16 logs right at / after midnight
        self.assertIn("boundary-log-dec16-midnight-exact", bodies)
        self.assertIn("boundary-log-dec16-midnight-plus1us", bodies)
        self.assertIn("boundary-log-dec16-midnight-plus1s", bodies)
        # Earlier Dec 15 morning should NOT match (outside timestamp range)
        self.assertNotIn("boundary-log-dec15-morning", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_exactly_midnight_from(self):
        """date_from exactly at midnight — toStartOfDay still equals that day."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-16 00:00:00Z", "2025-12-16 00:00:012Z"))
        self.assertIn("boundary-log-dec16-midnight-exact", bodies)
        self.assertIn("boundary-log-dec16-midnight-plus1us", bodies)
        self.assertIn("boundary-log-dec16-midnight-plus1s", bodies)
        # Dec 15 logs should NOT appear (time_bucket Dec 15 < toStartOfDay(Dec 16))
        self.assertNotIn("boundary-log-dec15-2359", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_exactly_midnight_to(self):
        """date_to exactly at midnight Dec 17 — toStartOfDay(date_to) = Dec 17, so Dec 17 time_bucket included."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-17 00:00:00Z", "2025-12-17 00:00:00.000002Z"))
        self.assertIn("boundary-log-dec17-midnight-exact", bodies)
        self.assertIn("boundary-log-dec17-midnight-plus1us", bodies)
        # Dec 16 logs should NOT appear
        self.assertNotIn("boundary-log-dec16-midnight-exact", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_multi_day_span(self):
        """Query spanning Dec 14 noon → Dec 18 early should include all boundary logs."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-14 00:00:00Z", "2025-12-19 00:00:00Z"))
        expected = {
            "boundary-log-dec14-noon",
            "boundary-log-dec15-morning",
            "boundary-log-dec15-2359",
            "boundary-log-dec15-2359-last-micro",
            "boundary-log-dec16-midnight-exact",
            "boundary-log-dec16-midnight-plus1us",
            "boundary-log-dec16-midnight-plus1s",
            "boundary-log-dec17-midnight-exact",
            "boundary-log-dec17-midnight-plus1us",
            "boundary-log-dec17-afternoon",
            "boundary-log-dec18-early",
        }
        self.assertEqual(bodies, expected)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_narrow_window_around_midnight(self):
        """Very narrow window: last microsecond of Dec 15 → first microsecond of Dec 16.
        Both days' time_buckets must be scanned."""
        bodies = self._boundary_bodies(
            self._boundary_query("2025-12-15 23:59:59.999999Z", "2025-12-16 00:00:00.000002Z")
        )
        self.assertIn("boundary-log-dec15-2359-last-micro", bodies)
        self.assertIn("boundary-log-dec16-midnight-exact", bodies)
        self.assertIn("boundary-log-dec16-midnight-plus1us", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_excludes_outside_days(self):
        """Query for Dec 15 only — Dec 14 and Dec 16+ must not appear."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-15 00:00:00Z", "2025-12-16 00:00:00Z"))
        self.assertNotIn("boundary-log-dec14-noon", bodies)
        self.assertNotIn("boundary-log-dec16-midnight-exact", bodies)
        self.assertNotIn("boundary-log-dec17-midnight-exact", bodies)
        self.assertNotIn("boundary-log-dec18-early", bodies)

    @freeze_time("2025-12-19T00:00:00Z")
    def test_time_bucket_date_to_midday_does_not_leak_next_day(self):
        """date_to in the middle of Dec 17 — Dec 18 logs must NOT appear."""
        bodies = self._boundary_bodies(self._boundary_query("2025-12-17 00:00:00Z", "2025-12-17 15:00:00Z"))
        self.assertIn("boundary-log-dec17-midnight-exact", bodies)
        self.assertIn("boundary-log-dec17-midnight-plus1us", bodies)
        self.assertIn("boundary-log-dec17-afternoon", bodies)
        self.assertNotIn("boundary-log-dec18-early", bodies)

    # ── _normalize_filter_group tests ──────────────────────────────────

    _FLAT_FILTERS = [
        {"key": "message", "operator": "icontains", "type": "log", "value": "error"},
        {"key": "http.status_code", "operator": "exact", "type": "log_attribute", "value": "500"},
    ]

    @parameterized.expand(
        [
            ("none", None, {"type": "AND", "values": []}),
            ("empty_list", [], {"type": "AND", "values": []}),
            ("flat_list", _FLAT_FILTERS, {"type": "AND", "values": [{"type": "AND", "values": _FLAT_FILTERS}]}),
            (
                "already_nested",
                {"type": "AND", "values": [{"type": "AND", "values": []}]},
                {"type": "AND", "values": [{"type": "AND", "values": []}]},
            ),
        ]
    )
    def test_normalize_filter_group(self, _name, input_value, expected):
        from products.logs.backend.api import LogsViewSet

        self.assertEqual(LogsViewSet._normalize_filter_group(input_value), expected)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_query_with_flat_filter_group(self):
        """The query endpoint normalizes flat filter arrays to nested PropertyGroupFilter."""
        query_params = {
            "dateRange": {"date_from": "2025-12-16 09:32:36.178572Z", "date_to": None},
            "limit": 10,
            "filterGroup": [
                {
                    "key": "k8s.pod.name",
                    "value": "efs-csi-node",
                    "operator": "icontains",
                    "type": "log_resource_attribute",
                },
            ],
        }
        response = self._make_logs_api_request(query_params)
        self.assertGreater(len(response["results"]), 0)
        for result in response["results"]:
            self.assertIn("efs-csi-node", result["resource_attributes"].get("k8s.pod.name", ""))

    @freeze_time("2025-12-16T10:33:00Z")
    def test_query_with_empty_flat_filter_group(self):
        """Empty flat filter array should return results (no filtering)."""
        query_params = {
            "dateRange": {"date_from": "2025-12-16T10:32:36.184820Z", "date_to": None},
            "limit": 10,
            "filterGroup": [],
        }
        response = self._make_logs_api_request(query_params)
        self.assertGreater(len(response["results"]), 0)


class TestNumericDistinctIdLinking(ClickhouseTestMixin, APIBaseTest):
    """End-to-end reproduction of the Circleback bug: logs whose person-pivot attribute
    holds a numeric-looking string (e.g. a customer's own user PK `69339`) must link to
    that person, and exact matching must not collide across zero-padded / float-equal
    variants (`"7"` vs `"007"`). Inserts real rows and queries through the API so the
    `__str` vs `__float` map routing is exercised against stored data, not just asserted
    on generated SQL."""

    def _insert_logs(self, rows: list[dict]) -> None:
        full = [
            {
                "uuid": str(UUIDT()),
                "team_id": self.team.id,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "web",
                "resource_attributes": {},
                **row,
            }
            for row in rows
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in full))

    def _query_pivot(self, values: list[str], key: str = "posthogDistinctId") -> list[dict]:
        query_params = {
            "dateRange": {"date_from": "2026-01-01T09:00:00Z", "date_to": "2026-01-01T11:00:00Z"},
            "limit": 50,
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": key, "value": values, "operator": "exact", "type": "log_attribute"}],
                    }
                ],
            },
        }
        response = self.client.post(f"/api/projects/{self.team.id}/logs/query", data={"query": query_params})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["results"]

    def test_all_numeric_distinct_id_links(self):
        """A person whose only distinct_id is the numeric string `69339` (no anonymous UUID
        to mask the routing) still matches their logs. Pre-fix this routed to `__float` and
        silently missed."""
        self._insert_logs(
            [
                {
                    "timestamp": "2026-01-01 10:00:00.000000",
                    "body": "numeric-user-log",
                    "attributes_map_str": {"posthogDistinctId__str": "69339"},
                }
            ]
        )
        results = self._query_pivot(["69339"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["body"], "numeric-user-log")

    def test_zero_padded_and_float_equal_values_do_not_collide(self):
        """`"7"`, `"007"`, and `"7.0"` all coerce to the float 7.0 — under `__float` an exact
        filter for one would wrongly return all three (cross-person log leakage). Under `__str`
        each is an exact, distinct string."""
        self._insert_logs(
            [
                {
                    "timestamp": "2026-01-01 10:00:00.000000",
                    "body": "user-7",
                    "attributes_map_str": {"posthogDistinctId__str": "7"},
                },
                {
                    "timestamp": "2026-01-01 10:00:01.000000",
                    "body": "user-007",
                    "attributes_map_str": {"posthogDistinctId__str": "007"},
                },
                {
                    "timestamp": "2026-01-01 10:00:02.000000",
                    "body": "user-7-dot-0",
                    "attributes_map_str": {"posthogDistinctId__str": "7.0"},
                },
            ]
        )
        bodies = {r["body"] for r in self._query_pivot(["7"])}
        self.assertEqual(bodies, {"user-7"}, f"exact match for '7' leaked other people's logs: {bodies}")

    def test_large_numeric_distinct_id_keeps_precision(self):
        """A numeric distinct_id beyond float64 integer precision (> 2^53) must match exactly.
        Under `__float` it would round and collide/mismatch; under `__str` it's exact."""
        big = "9007199254740993"  # 2^53 + 1, not representable exactly as float64
        neighbor = "9007199254740992"  # 2^53, the value `big` rounds to
        self._insert_logs(
            [
                {
                    "timestamp": "2026-01-01 10:00:00.000000",
                    "body": "big-id",
                    "attributes_map_str": {"posthogDistinctId__str": big},
                },
                {
                    "timestamp": "2026-01-01 10:00:01.000000",
                    "body": "neighbor-id",
                    "attributes_map_str": {"posthogDistinctId__str": neighbor},
                },
            ]
        )
        bodies = {r["body"] for r in self._query_pivot([big])}
        self.assertEqual(bodies, {"big-id"}, f"large numeric id lost precision / collided: {bodies}")
