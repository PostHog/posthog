from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_modeling.backend.facade.api import sync_saved_query_to_dag
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Edge, Node
from products.product_analytics.backend.facade.api import insight_references
from products.product_analytics.backend.facade.models import Insight
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
            (
                "view_inside_a_join_condition",
                _sql("SELECT * FROM events JOIN persons ON events.person_id IN (SELECT id FROM orders_view)"),
                {"events", "persons", "orders_view"},
            ),
            (
                "nested_visualization_wrappers",
                {"kind": "InsightVizNode", "source": _sql("SELECT * FROM orders_view")},
                {"orders_view"},
            ),
            ("trends_without_a_warehouse_series", _trends(PAGEVIEWS), set()),
            (
                "all_time_warehouse_series",
                {
                    "kind": "InsightVizNode",
                    "source": {"kind": "TrendsQuery", "series": [CHARGES_SERIES], "dateRange": {"date_from": "all"}},
                },
                {"stripe_charges"},
            ),
            (
                "hogql_filter_without_a_warehouse_series",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [PAGEVIEWS],
                        "properties": [{"type": "hogql", "key": "person_id IN (SELECT id FROM orders_view)"}],
                    },
                },
                {"orders_view"},
            ),
            (
                "hogql_aggregation",
                _trends({**PAGEVIEWS, "math": "hogql", "math_hogql": "sum(id IN (SELECT id FROM orders_view))"}),
                {"orders_view"},
            ),
            (
                "hogql_breakdown",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [PAGEVIEWS],
                        "breakdownFilter": {
                            "breakdown_type": "hogql",
                            "breakdown": "id IN (SELECT id FROM orders_view)",
                        },
                    },
                },
                {"orders_view"},
            ),
        ]
    )
    def test_reads_names_the_way_the_query_writes_them(self, _name: str, query: dict, expected: set[str]) -> None:
        self.assertEqual(insight_table_names(query), expected)


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

    def test_model_saves_keep_lineage_in_step_with_the_persisted_query(self) -> None:
        for name in ("orders_view", "refunds_view"):
            view = DataWarehouseSavedQuery.objects.create(
                team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT event AS id FROM events"}
            )
            sync_saved_query_to_dag(view)
        query = _sql("SELECT * FROM orders_view")
        insight = Insight.objects.create(team=self.team, name="Orders", query=query)

        self.assertEqual(
            list(Edge.objects.filter(target__insight_id=insight.id).values_list("source__name", flat=True)),
            ["orders_view"],
        )

        query["source"]["query"] = "SELECT * FROM refunds_view"
        insight.save(update_fields=["query"])
        self.assertEqual(
            list(Edge.objects.filter(target__insight_id=insight.id).values_list("source__name", flat=True)),
            ["refunds_view"],
        )

        insight.name = "Refunds"
        query["source"]["query"] = "SELECT * FROM orders_view"
        insight.save(update_fields=["name"])
        node = Node.objects.get(insight_id=insight.id)
        self.assertEqual(node.name, "Refunds")
        self.assertEqual(
            list(Edge.objects.filter(target=node).values_list("source__name", flat=True)), ["refunds_view"]
        )

        insight.query = _sql("SELECT count() FROM events")
        insight.save(update_fields=["query"])
        self.assertFalse(Node.objects.filter(insight_id=insight.id).exists())

    def test_live_reader_names_are_fetched_without_loading_each_insights_query(self) -> None:
        first = Insight.objects.create(team=self.team, name="Orders", query=_sql("SELECT 1"))
        second = Insight.objects.create(team=self.team, derived_name="Refunds", query=_sql("SELECT 2"))
        deleted = Insight.objects.create(team=self.team, name="Deleted", deleted=True)

        with self.assertNumQueries(1):
            references = insight_references(team_id=self.team.id, insight_ids=[first.id, second.id, deleted.id])

        self.assertEqual(
            [(reference.id, reference.name) for reference in references], [(first.id, "Orders"), (second.id, "Refunds")]
        )
