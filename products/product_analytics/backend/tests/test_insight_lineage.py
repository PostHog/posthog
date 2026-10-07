from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.product_analytics.backend.insight_lineage import insight_table_names, warehouse_dependency_names
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _sql(query: str) -> dict[str, Any]:
    return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": query}}


def _trends(*series: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": list(series)}}


PAGEVIEWS = {"kind": "EventsNode", "event": "$pageview"}
CHARGES_SERIES = {
    "kind": "DataWarehouseNode",
    "id": "stripe_charges",
    "table_name": "stripe_charges",
    "timestamp_field": "created_at",
    "distinct_id_field": "customer_id",
    "id_field": "id",
}


class TestInsightTableNames(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "views_inside_subqueries",
                {
                    "kind": "HogQLQuery",
                    "query": "SELECT count() FROM (SELECT * FROM orders_view) WHERE id IN (SELECT id FROM refunds_view)",
                },
                {"orders_view", "refunds_view"},
            ),
            (
                "view_inside_a_cte_body_without_the_cte_name",
                {"kind": "HogQLQuery", "query": "WITH recent AS (SELECT * FROM orders_view) SELECT * FROM recent"},
                {"orders_view"},
            ),
            (
                "data_visualization_node_with_a_dotted_source_table",
                _sql("SELECT * FROM orders_view JOIN stripe.charges AS charges ON charges.id = orders_view.id"),
                {"orders_view", "stripe.charges"},
            ),
            ("trends_without_a_warehouse_series", _trends(PAGEVIEWS), set()),
        ]
    )
    def test_reads_names_the_way_the_query_writes_them(self, _name: str, query: dict, expected: set[str]) -> None:
        self.assertEqual(insight_table_names(Team(id=1), query), expected)


class TestWarehouseDependencyNames(BaseTest):
    @parameterized.expand(
        [
            (
                "sql",
                _sql("SELECT * FROM orders_view JOIN events ON events.distinct_id = orders_view.id"),
                ["orders_view"],
            ),
            ("trends_with_a_warehouse_series", _trends(PAGEVIEWS, CHARGES_SERIES), ["stripe_charges"]),
        ]
    )
    def test_keeps_warehouse_tables_and_views_and_drops_posthog_tables(
        self, _name: str, query: dict, expected: list[str]
    ) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders_view", query={"kind": "HogQLQuery", "query": "SELECT event AS id FROM events"}
        )
        DataWarehouseTable.objects.create(team=self.team, name="stripe_charges", format="Parquet")

        self.assertEqual(warehouse_dependency_names(self.team, query), expected)
