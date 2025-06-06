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
from products.revenue_analytics.backend.utils import revenue_selects_from_database


class RevenueAnalyticsTaxonomyViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(methods=["GET"], detail=False)
    def values(self, request: Request, **kwargs):
        key = request.GET.get("key")
        database = create_hogql_database(team=self.team)

        query = None
        if key == "product":  # All products available from revenue analytics
            revenue_selects = revenue_selects_from_database(database)
            product_selects = [
                select["product"] for select in revenue_selects.values() if select["product"] is not None
            ]
            product_selects_union = ast.SelectSetQuery.create_from_queries(product_selects, set_operator="UNION ALL")

            query = ast.SelectQuery(
                select=[ast.Field(chain=["name"])],
                distinct=True,
                select_from=ast.JoinExpr(table=product_selects_union),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["name"]), order="ASC")],
            )

        values = []
        if query is not None:
            try:
                result = execute_hogql_query(query, team=self.team)
                values = [row[0] for row in result.results]
            except Exception as e:
                capture_exception(e)
                pass  # Just return an empty list if can't compute

        return Response([{"name": value} for value in values])
