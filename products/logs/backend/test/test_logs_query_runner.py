import os
import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

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

        # All filter types should be present
        self.assertIn("http.status_code__float", query_str)
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
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)
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
