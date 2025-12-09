from posthog.test.base import APIBaseTest, ClickhouseTestMixin

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

from posthog.clickhouse.client.connection import Workload

from products.logs.backend.logs_query_runner import LogsQueryRunner


class TestLogsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

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
        self.assertNotIn("(in(resource_fingerprint", query_str)

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
        self.assertIn("(in(resource_fingerprint", query_str)

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
        self.assertNotIn("(In(resource_fingerprint", query_str)

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
        self.assertIn("(in(resource_fingerprint", query_str)

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
        self.assertIn("(in(resource_fingerprint", query_str)
