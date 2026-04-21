from typing import cast

from posthoganalytics import capture_exception
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import DatabaseSchemaManagedViewTableKind, ProductKey

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.team.team import Team

from products.revenue_analytics.backend.joins import ensure_person_join_for_team, remove_person_join_for_team
from products.revenue_analytics.backend.views import RevenueAnalyticsBaseView
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS


# Extracted to a separate function to be reused in the TaxonomyAgentToolkit
def find_values_for_revenue_analytics_property(key: str, team: Team) -> list[str]:
    # Get the scope from before the first dot
    # and if there's no dot then it's the base case which is RevenueAnalyticsRevenueItemView
    scope, *chain = key.split(".")
    if len(chain) == 0:
        chain = [scope]
        scope = "revenue_analytics_revenue_item"

    database = Database.create_for(team=team)
    schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind(scope)]

    # Try and find the union view for this class
    views: list[RevenueAnalyticsBaseView] = []
    for view_name in database.get_view_names():
        if view_name.endswith(schema.source_suffix) or view_name.endswith(schema.events_suffix):
            view = database.get_table(view_name)
            views.append(cast(RevenueAnalyticsBaseView, view))

    if len(views) == 0:
        return []

    selects: list[ast.SelectQuery | ast.SelectSetQuery] = [
        ast.SelectQuery(select=[ast.Field(chain=["*"])], select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])))
        for view in views
    ]

    if len(selects) == 1:
        select_from = selects[0]
    else:
        select_from = ast.SelectSetQuery.create_from_queries(selects, set_operator="UNION ALL")

    query = ast.SelectQuery(
        select=[ast.Field(chain=chain)],  # type: ignore
        distinct=True,
        select_from=ast.JoinExpr(table=select_from),
        order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
    )

    values = []
    try:
        tag_queries(product=ProductKey.REVENUE_ANALYTICS, feature=Feature.QUERY)
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
            return Response({"results": [], "refreshing": False})

        values = find_values_for_revenue_analytics_property(key, self.team)
        return Response({"results": [{"name": value} for value in values], "refreshing": False})


class RevenueAnalyticsJoinSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=True)


class RevenueAnalyticsJoinViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    def create(self, request: Request, **kwargs):
        serializer = RevenueAnalyticsJoinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data["enabled"]:
            ensure_person_join_for_team(self.team.pk)
            msg = "Joins created successfully"
        else:
            remove_person_join_for_team(self.team.pk)
            msg = "Joins removed successfully"

        return Response({"detail": msg}, status=status.HTTP_200_OK)
