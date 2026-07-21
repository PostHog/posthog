import json
import base64

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    HogQLFilters,
    LogAttributesQuery,
    LogPropertyFilter,
    LogPropertyFilterType,
    LogsQuery,
    LogValuesQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client.connection import Workload

from products.logs.backend.archive_query_runners import (
    ArchivedLogAttributesQueryRunner,
    ArchivedLogFacetValuesQueryRunner,
    ArchivedLogsQueryRunner,
    ArchivedLogValuesQueryRunner,
    ArchivedSparklineQueryRunner,
)
from products.logs.backend.archive_routing import use_archive_requested
from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunner

DATE_RANGE = DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-02-15T23:59:59Z")


def _filter_group(*filters: LogPropertyFilter) -> PropertyGroupFilter:
    return PropertyGroupFilter(
        type=FilterLogicalOperator.AND_,
        values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=list(filters))],
    )


def _generated_sql(runner) -> str:
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
    return executor.clickhouse_prepared_ast.to_hogql()


class TestArchivedLogsQueryRunner(APIBaseTest):
    def test_queries_archive_table_with_log_date_pruning(self):
        query = LogsQuery(dateRange=DATE_RANGE, serviceNames=["web"], severityLevels=[], filterGroup=_filter_group())
        sql = _generated_sql(ArchivedLogsQueryRunner(query=query, team=self.team))

        self.assertIn("logs_archive", sql)
        self.assertIn("log_date", sql)
        # time_bucket and the live-logs kafka checkpoint only exist on the hot tables
        self.assertNotIn("time_bucket", sql)
        self.assertNotIn("logs_kafka_metrics", sql)

    def test_log_attribute_filter_keeps_raw_key(self):
        # The hot table's __str/__float typed-map suffixes resolve via property-groups config
        # keyed to logs_distributed; on the archive a suffixed key would silently match nothing.
        query = LogsQuery(
            dateRange=DATE_RANGE,
            serviceNames=[],
            severityLevels=[],
            filterGroup=_filter_group(
                LogPropertyFilter(
                    key="http.status_code",
                    operator=PropertyOperator.EXACT,
                    type=LogPropertyFilterType.LOG_ATTRIBUTE,
                    value="500",
                )
            ),
        )
        sql = _generated_sql(ArchivedLogsQueryRunner(query=query, team=self.team))

        self.assertIn("http.status_code", sql)
        self.assertNotIn("__str", sql)
        self.assertNotIn("__float", sql)
        # The filter must resolve against the archive's `attributes` map, not the event `properties`
        # column (property_to_expr keys off the log_attribute type, so scope can't misroute it).
        self.assertIn("attributes", sql)
        self.assertNotIn("properties", sql)

    @parameterized.expand(
        [
            ("positive", PropertyOperator.EXACT),
            ("negative", PropertyOperator.IS_NOT),
        ]
    )
    def test_resource_attribute_filter_is_map_predicate(self, _name, operator):
        # The hot path routes resource attribute filters through log_attributes subqueries;
        # no such rollup exists for the archive, so they must hit the map directly.
        query = LogsQuery(
            dateRange=DATE_RANGE,
            serviceNames=[],
            severityLevels=[],
            filterGroup=_filter_group(
                LogPropertyFilter(
                    key="k8s.container.name",
                    operator=operator,
                    type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                    value="nginx",
                )
            ),
        )
        sql = _generated_sql(ArchivedLogsQueryRunner(query=query, team=self.team))

        self.assertIn("resource_attributes", sql)
        self.assertNotIn("log_attributes", sql)
        self.assertNotIn("arrayAll", sql)

    @parameterized.expand(
        [
            ("is_set", PropertyOperator.IS_SET, "mapContains"),
            ("is_not_set", PropertyOperator.IS_NOT_SET, "not(mapContains"),
        ]
    )
    def test_resource_attribute_set_operators_use_map_contains(self, _name, operator, expected):
        # Map subscripts return '' for absent keys, so a != NULL check would be constant-true.
        query = LogsQuery(
            dateRange=DATE_RANGE,
            serviceNames=[],
            severityLevels=[],
            filterGroup=_filter_group(
                LogPropertyFilter(
                    key="k8s.container.name",
                    operator=operator,
                    type=LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE,
                )
            ),
        )
        sql = _generated_sql(ArchivedLogsQueryRunner(query=query, team=self.team))

        self.assertIn(expected, sql)

    def test_cursor_pagination_prunes_on_log_date(self):
        cursor = base64.b64encode(
            json.dumps({"timestamp": "2024-01-20T12:00:00+00:00", "uuid": "abc"}).encode()
        ).decode()
        query = LogsQuery(
            dateRange=DATE_RANGE, serviceNames=[], severityLevels=[], filterGroup=_filter_group(), after=cursor
        )
        sql = _generated_sql(ArchivedLogsQueryRunner(query=query, team=self.team))

        self.assertIn("lessOrEquals(log_date", sql)
        self.assertNotIn("time_bucket", sql)


class TestArchivedSparklineQueryRunner(APIBaseTest):
    def test_unfiltered_query_uses_preaggregated_table(self):
        query = LogsQuery(
            dateRange=DATE_RANGE, serviceNames=["web"], severityLevels=["error"], filterGroup=_filter_group()
        )
        sql = _generated_sql(ArchivedSparklineQueryRunner(query=query, team=self.team))

        self.assertIn("logs_archive_sparkline", sql)
        self.assertIn("event_count", sql)

    @parameterized.expand(
        [
            ("search_term", {"searchTerm": "error"}),
            (
                "attribute_filter",
                {
                    "filterGroup": _filter_group(
                        LogPropertyFilter(
                            key="http.status_code",
                            operator=PropertyOperator.EXACT,
                            type=LogPropertyFilterType.LOG_ATTRIBUTE,
                            value="500",
                        )
                    )
                },
            ),
        ]
    )
    def test_search_or_attribute_filters_fall_back_to_raw_scan(self, _name, extra):
        # The pre-agg table has no body or attribute dims; routing such a query to it would
        # silently return unfiltered counts.
        query = LogsQuery(
            dateRange=DATE_RANGE, serviceNames=[], severityLevels=[], **{"filterGroup": _filter_group(), **extra}
        )
        sql = _generated_sql(ArchivedSparklineQueryRunner(query=query, team=self.team))

        self.assertNotIn("logs_archive_sparkline", sql)
        self.assertIn("logs_archive", sql)
        # the archive has no byte counts or minute-aggregate projection
        self.assertNotIn("_bytes_uncompressed", sql)
        self.assertNotIn("toStartOfMinute", sql)


class TestArchivedAttributeRunners(APIBaseTest):
    def test_attribute_keys_aggregate_raw_map(self):
        query = LogAttributesQuery(attributeType="log", search="http", limit=100, offset=0, dateRange=DATE_RANGE)
        sql = _generated_sql(ArchivedLogAttributesQueryRunner(query=query, team=self.team))

        self.assertIn("logs_archive", sql)
        self.assertIn("mapKeys(attributes)", sql)
        self.assertNotIn("log_attributes", sql)

    def test_attribute_value_search_uses_map_items(self):
        query = LogAttributesQuery(
            attributeType="resource", search="nginx", searchValues=True, limit=100, offset=0, dateRange=DATE_RANGE
        )
        sql = _generated_sql(ArchivedLogAttributesQueryRunner(query=query, team=self.team))

        self.assertIn("mapItems(resource_attributes)", sql)
        self.assertIn("'key'", sql)
        self.assertIn("'value'", sql)

    def test_values_query_reads_map_subscript(self):
        query = LogValuesQuery(
            attributeType="log", attributeKey="http.status_code", search="", limit=100, offset=0, dateRange=DATE_RANGE
        )
        sql = _generated_sql(ArchivedLogValuesQueryRunner(query=query, team=self.team))

        self.assertIn("logs_archive", sql)
        self.assertIn("mapContains(attributes, 'http.status_code')", sql)
        self.assertNotIn("log_attributes", sql)


class TestArchivedLogFacetValuesQueryRunner(APIBaseTest):
    def test_column_facet_groups_archive_table(self):
        query = LogsQuery(dateRange=DATE_RANGE, serviceNames=[], severityLevels=[], filterGroup=_filter_group())
        sql = _generated_sql(ArchivedLogFacetValuesQueryRunner(query=query, team=self.team, facet_field="service_name"))

        self.assertIn("logs_archive", sql)
        self.assertIn("log_date", sql)
        self.assertIn("service_name", sql)

    def test_resource_facet_reads_map_not_rollup(self):
        # The hot resource facet reads the log_attributes rollup, which has no archive equivalent —
        # the archive runner must group the raw resource_attributes map instead.
        query = LogsQuery(dateRange=DATE_RANGE, serviceNames=[], severityLevels=[], filterGroup=_filter_group())
        sql = _generated_sql(
            ArchivedLogFacetValuesQueryRunner(
                query=query, team=self.team, facet_resource_attribute="k8s.namespace.name"
            )
        )

        self.assertIn("logs_archive", sql)
        self.assertIn("resource_attributes", sql)
        self.assertIn("k8s.namespace.name", sql)
        self.assertNotIn("log_attributes", sql)


class TestArchiveRouting(APIBaseTest):
    @parameterized.expand(
        [
            ("flag_on_requested", True, True, True),
            ("flag_on_not_requested", True, False, False),
            ("flag_off_requested", False, True, False),
            ("flag_off_not_requested", False, False, False),
        ]
    )
    def test_use_archive_requested(self, _name, flag_enabled, requested, expected):
        with patch("products.logs.backend.archive_routing.posthoganalytics.feature_enabled", return_value=flag_enabled):
            result = use_archive_requested(self.user, self.team, requested)
        self.assertEqual(result, expected)

    def test_flag_service_failure_degrades_to_hot_path(self):
        with patch(
            "products.logs.backend.archive_routing.posthoganalytics.feature_enabled",
            side_effect=Exception("flag service down"),
        ):
            self.assertFalse(use_archive_requested(self.user, self.team, True))


class TestArchiveViewsetRouting(APIBaseTest):
    def _post_query(self, query: dict):
        return self.client.post(f"/api/projects/{self.team.id}/logs/query", data={"query": query}, format="json")

    @parameterized.expand(
        [
            ("flag_on_requested", True, True, True),
            ("flag_off_requested", False, True, False),
            ("flag_on_not_requested", True, False, False),
        ]
    )
    def test_query_endpoint_routes_on_use_archive(self, _name, flag_enabled, use_archive, expect_archive):
        with (
            patch(
                "products.logs.backend.archive_routing.posthoganalytics.feature_enabled",
                return_value=flag_enabled,
            ),
            patch.object(
                ArchivedLogsQueryRunner, "_calculate", return_value=LogsQueryResponse(results=[])
            ) as archive_calc,
            patch.object(LogsQueryRunner, "_calculate", return_value=LogsQueryResponse(results=[])) as hot_calc,
        ):
            response = self._post_query({"dateRange": {"date_from": "-30d"}, "useArchive": use_archive})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["usedArchive"], expect_archive)
        if expect_archive:
            archive_calc.assert_called()
            hot_calc.assert_not_called()
        else:
            hot_calc.assert_called()

    def test_live_tail_never_routes_to_archive(self):
        with (
            patch(
                "products.logs.backend.archive_routing.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch.object(
                ArchivedLogsQueryRunner, "_calculate", return_value=LogsQueryResponse(results=[])
            ) as archive_calc,
            patch.object(LogsQueryRunner, "_calculate", return_value=LogsQueryResponse(results=[])),
        ):
            response = self._post_query(
                {
                    "dateRange": {"date_from": "-30d"},
                    "useArchive": True,
                    "liveLogsCheckpoint": "2024-06-15T12:00:00+00:00",
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["usedArchive"])
        archive_calc.assert_not_called()
