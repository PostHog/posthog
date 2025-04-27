# NOTE: This isn't testing any of the custom Revenue Analytics code,
# but rather testing the revenue code in insights/trends/aggregation_operations.py
from decimal import Decimal
from typing import Any, Optional

from freezegun import freeze_time
from datetime import datetime

from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQuery, EventsNode, DataWarehouseNode
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    IntervalType,
    PropertyMathType,
    TaxonomicFilterGroupType,
    RevenueCurrencyPropertyConfig,
    CurrencyCode,
    CachedTrendsQueryResponse,
)
from posthog.warehouse.models import (
    DataWarehouseTable,
    DataWarehouseCredential,
)

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
    patch_clickhouse_client_execute,
)


@snapshot_clickhouse_queries
class TestRevenueAnalyticsInsights(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="product_sold"):
        person_result = []
        for id, events in data:
            with freeze_time(events[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )

            for timestamp, session_id, properties in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id, **properties},
                )

        return person_result

    def _create_data_warehouse_table(
        self, name: str, distinct_id_column: str, revenue_column: str, timestamp_column: str, currency_column: str
    ):
        return DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,  # Parquet is commonly used in other tests
            team=self.team,
            credential=DataWarehouseCredential.objects.create(
                team=self.team,
                access_key="test-key",
                access_secret="test-secret",
            ),
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                distinct_id_column: {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                revenue_column: {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                timestamp_column: {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
                currency_column: {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
            },
        )

    def _create_query_runner(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: list[EventsNode | DataWarehouseNode],
        properties: Optional[Any] = None,
    ) -> TrendsQueryRunner:
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            series=series,
            properties=properties,
        )

        return TrendsQueryRunner(team=self.team, query=query)

    def test_events_revenue_currency_property(self):
        # Storing as USD here
        self._create_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 100, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 200, "currency": "USD"}),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 150, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 250, "currency": "USD"}),
                    ],
                ),
            ]
        )

        # Using the `currency` field, and because base is USD will keep value constant
        query_runner = self._create_query_runner(
            date_from="2024-01-01",
            date_to="2024-01-02",
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="product_sold",
                    math=PropertyMathType.SUM,
                    math_property="revenue",
                    math_property_revenue_currency=RevenueCurrencyPropertyConfig(property="currency"),
                )
            ],
        )

        response = query_runner.run()
        assert isinstance(response, CachedTrendsQueryResponse)
        results = response.results[0]
        assert results["data"] == [Decimal("250"), Decimal("450")]

    def test_events_revenue_currency_static(self):
        # Storing as USD here
        self._create_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 100, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 200, "currency": "USD"}),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2024-01-01", str(uuid7()), {"revenue": 150, "currency": "USD"}),
                        ("2024-01-02", str(uuid7()), {"revenue": 250, "currency": "USD"}),
                    ],
                ),
            ]
        )

        # But rather than using the `currency` field, we're treating `revenue` as static GBP
        query_runner = self._create_query_runner(
            date_from="2024-01-01",
            date_to="2024-01-02",
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="product_sold",
                    math=PropertyMathType.SUM,
                    math_property="revenue",
                    math_property_revenue_currency=RevenueCurrencyPropertyConfig(static=CurrencyCode.GBP),
                )
            ],
        )

        response = query_runner.run()
        assert isinstance(response, CachedTrendsQueryResponse)
        results = response.results[0]
        assert results["data"] == [Decimal("318.3902190523"), Decimal("569.764497341")]

    def test_dw_revenue_currency_property(self):
        self._create_data_warehouse_table("database_with_revenue_column", "id", "revenue", "timestamp", "currency")

        # Spy on the `clichhouse_driver.Client.execute` method to avoid querying the data warehouse tables
        def execute_wrapper(original_client_execute, query, *args, **kwargs):
            if (
                "Parquet" in query
            ):  # Detecting the query that queries the data warehouse table, using the format of the table name
                return (
                    [
                        (
                            [datetime(2024, 1, 1), datetime(2024, 1, 2, 0, 0)],
                            [Decimal("318.3902190523"), Decimal("569.764497341")],
                        )
                    ],
                    [("date", "Array(DateTime('UTC'))"), ("total", "Array(Decimal(76, 10))")],
                )

            return original_client_execute(query, *args, **kwargs)

        # Don't assert on the output, we're only interested in the queries that were executed
        with patch_clickhouse_client_execute(execute_wrapper):
            self._create_query_runner(
                date_from="2024-01-01",
                date_to="2024-01-02",
                interval=IntervalType.DAY,
                series=[
                    DataWarehouseNode(
                        id="database_with_revenue_column",
                        name="database_with_revenue_column",
                        table_name="database_with_revenue_column",
                        math=PropertyMathType.SUM,
                        math_property="revenue",
                        math_property_type=TaxonomicFilterGroupType.DATA_WAREHOUSE_PROPERTIES,
                        math_property_revenue_currency={"property": "currency"},
                        id_field="id",
                        distinct_id_field="id",
                        timestamp_field="timestamp",
                    )
                ],
            ).run()

    def test_dw_revenue_currency_static(self):
        self._create_data_warehouse_table("database_with_revenue_column", "id", "revenue", "timestamp", "currency")

        # Spy on the `clichhouse_driver.Client.execute` method to avoid querying the data warehouse tables
        def execute_wrapper(original_client_execute, query, *args, **kwargs):
            if (
                "Parquet" in query
            ):  # Detecting the query that queries the data warehouse table, using the format of the table name
                return (
                    [
                        (
                            [datetime(2024, 1, 1), datetime(2024, 1, 2, 0, 0)],
                            [Decimal("318.3902190523"), Decimal("569.764497341")],
                        )
                    ],
                    [("date", "Array(DateTime('UTC'))"), ("total", "Array(Decimal(76, 10))")],
                )

            return original_client_execute(query, *args, **kwargs)

        # Don't assert on the output, we're only interested in the queries that were executed
        with patch_clickhouse_client_execute(execute_wrapper):
            self._create_query_runner(
                date_from="2024-01-01",
                date_to="2024-01-02",
                interval=IntervalType.DAY,
                series=[
                    DataWarehouseNode(
                        id="database_with_revenue_column",
                        name="database_with_revenue_column",
                        table_name="database_with_revenue_column",
                        math=PropertyMathType.SUM,
                        math_property="revenue",
                        math_property_type=TaxonomicFilterGroupType.DATA_WAREHOUSE_PROPERTIES,
                        math_property_revenue_currency={"static": "GBP"},
                        id_field="id",
                        distinct_id_field="id",
                        timestamp_field="timestamp",
                    )
                ],
            ).run()
