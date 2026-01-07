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
        assert "service.name" in query_str
        assert "http.method" in query_str
        # Log attributes use resource_fingerprint filtering for optimization
        assert "(in(resource_fingerprint" in query_str

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
        assert "k8s.container.name" in query_str
        assert "k8s.pod.name" in query_str
        assert "(in(resource_fingerprint" in query_str

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
        assert "k8s.container.name" in query_str
        assert "notIn(resource_fingerprint" in query_str
        assert "(In(resource_fingerprint" not in query_str

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
        assert "http.status_code__float" in query_str
        assert "service.name" in query_str
        assert "message" in query_str
        assert "service.name__str" not in query_str
        assert "message__str" not in query_str
        assert "(in(resource_fingerprint" in query_str

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
        assert "service.name" in query_str
        assert "service.namespace" in query_str
        assert "notIn(resource_fingerprint" in query_str
        assert "(in(resource_fingerprint" in query_str


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
        assert response.status_code == expected_status
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
        assert len(response["results"]) == 50
        assert not response["hasMore"]
        assert len(queries) == 1

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
        assert len(response["results"]) == 50
        assert response["hasMore"]
        assert len(queries) == 1

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
        assert len(response["results"]) == 101
        assert len(queries) == 2

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
        assert len(response["results"]) == 1
        assert len(queries) == 2

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
        assert len(response["results"]) == 0
        assert len(queries) == 2

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
        assert len(response["results"]) == 10
        assert len(queries) == 2

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
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "x_forwarded_proto"
        assert data["results"][0]["propertyFilterType"] == "log_attribute"

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
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data[0]["name"] == "cdp-legacy-events-consumer"

        response = self.client.get(
            f"/api/projects/{self.team.id}/logs/values",
            {
                "dateRange": '{"date_from": "2025-12-16T10:32:36.184820Z", "date_to": null}',
                "attribute_type": "log",
                "limit": "10",
                "offset": "0",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
