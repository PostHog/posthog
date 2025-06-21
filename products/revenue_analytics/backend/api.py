from typing import cast
from rest_framework.viewsets import GenericViewSet
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.request import Request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.hogql import ast
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import execute_hogql_query
from products.revenue_analytics.backend.utils import (
    REVENUE_SELECT_OUTPUT_CUSTOMER_KEY,
    REVENUE_SELECT_OUTPUT_PRODUCT_KEY,
    REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY,
    RevenueSelectOutput,
    revenue_selects_from_database,
)


class RevenueAnalyticsTaxonomyViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(methods=["GET"], detail=False)
    def values(self, request: Request, **kwargs):
        key = request.GET.get("key")
        database = create_hogql_database(team=self.team)
        revenue_selects = revenue_selects_from_database(database)

        query = None
        values = []
        if key == "product":  # All products available from revenue analytics
            query = ast.SelectQuery(
                select=[ast.Field(chain=["name"])],
                distinct=True,
                select_from=ast.JoinExpr(table=self._product_selects(revenue_selects)),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["name"]), order="ASC")],
            )
        elif key == "cohort":  # All cohorts available from revenue analytics
            query = ast.SelectQuery(
                select=[ast.Field(chain=["cohort"])],
                distinct=True,
                select_from=ast.JoinExpr(table=self._customer_selects(revenue_selects)),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["cohort"]), order="ASC")],
            )
        elif key == "country":  # All countries available from revenue analytics
            query = ast.SelectQuery(
                select=[ast.Field(chain=["country"])],
                distinct=True,
                select_from=ast.JoinExpr(table=self._customer_selects(revenue_selects)),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["country"]), order="ASC")],
            )
        elif key == "coupon":  # All coupons available from revenue analytics
            query = ast.SelectQuery(
                select=[ast.Field(chain=["coupon"])],
                distinct=True,
                select_from=ast.JoinExpr(table=self._invoice_item_selects(revenue_selects)),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["coupon"]), order="ASC")],
            )
        elif key == "coupon_id":  # All coupon IDs available from revenue analytics
            query = ast.SelectQuery(
                select=[ast.Field(chain=["coupon_id"])],
                distinct=True,
                select_from=ast.JoinExpr(table=self._invoice_item_selects(revenue_selects)),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["coupon_id"]), order="ASC")],
            )
        elif key == "source":  # All sources available from revenue analytics
            values = list(revenue_selects.keys())

        if query is not None:
            try:
                result = execute_hogql_query(query, team=self.team)
                values = [row[0] for row in result.results]
            except Exception as e:
                capture_exception(e)
                pass  # Just return an empty list if can't compute

        return Response([{"name": value} for value in values])

    def _product_selects(self, revenue_selects: RevenueSelectOutput) -> ast.SelectSetQuery:
        product_selects: list[ast.SelectQuery] = [
            cast(ast.SelectQuery, select[REVENUE_SELECT_OUTPUT_PRODUCT_KEY])
            for select in revenue_selects.values()
            if select[REVENUE_SELECT_OUTPUT_PRODUCT_KEY] is not None
        ]

        return ast.SelectSetQuery.create_from_queries(product_selects, set_operator="UNION ALL")

    def _customer_selects(self, revenue_selects: RevenueSelectOutput) -> ast.SelectSetQuery:
        customer_selects: list[ast.SelectQuery] = [
            cast(ast.SelectQuery, select[REVENUE_SELECT_OUTPUT_CUSTOMER_KEY])
            for select in revenue_selects.values()
            if select[REVENUE_SELECT_OUTPUT_CUSTOMER_KEY] is not None
        ]

        return ast.SelectSetQuery.create_from_queries(customer_selects, set_operator="UNION ALL")

    def _invoice_item_selects(self, revenue_selects: RevenueSelectOutput) -> ast.SelectSetQuery:
        invoice_item_selects: list[ast.SelectQuery] = [
            cast(ast.SelectQuery, select[REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY])
            for select in revenue_selects.values()
            if select[REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY] is not None
        ]

        return ast.SelectSetQuery.create_from_queries(invoice_item_selects, set_operator="UNION ALL")
