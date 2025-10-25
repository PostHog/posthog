from posthoganalytics import capture_exception
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql import ast
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import Team

from products.revenue_analytics.backend.views import KIND_TO_CLASS, RevenueAnalyticsBaseView


# Extracted to a separate function to be reused in the TaxonomyAgentToolkit
def find_values_for_revenue_analytics_property(key: str, team: Team) -> list[str]:
    # Get the scope from before the first dot
    # and if there's no dot then it's the base case which is RevenueAnalyticsRevenueItemView
    scope, *chain = key.split(".")
    if len(chain) == 0:
        chain = [scope]
        scope = "revenue_analytics_revenue_item"

    database = create_hogql_database(team=team)
    view_class = KIND_TO_CLASS[DatabaseSchemaManagedViewTableKind(scope)]

    # Try and find the union view for this class
    union_view: RevenueAnalyticsBaseView | None = None
    for view_name in database.get_views():
        view = database.get_table(view_name)
        if isinstance(view, view_class) and view.union_all:
            union_view = view
            break

    if union_view is None:
        return []

    query = ast.SelectQuery(
        select=[ast.Field(chain=chain)],  # type: ignore
        distinct=True,
        select_from=ast.JoinExpr(table=ast.Field(chain=[union_view.name])),
        order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
    )

    values = []
    try:
        result = execute_hogql_query(query, team=team)
        values = [row[0] for row in result.results]
    except Exception as e:
        capture_exception(e)
        pass  # Just return an empty list if can't compute

    return values


class RevenueAnalyticsTaxonomyViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(methods=["GET"], detail=False)
    def values(self, request: Request, **kwargs):
        key = request.GET.get("key")
        if key is None:
            return Response([])

        values = find_values_for_revenue_analytics_property(key, self.team)
        return Response([{"name": value} for value in values])
