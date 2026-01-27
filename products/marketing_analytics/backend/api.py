import structlog
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import SourceMap

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import DEFAULT_CURRENCY

from products.data_warehouse.backend.models import DataWarehouseTable
from products.marketing_analytics.backend.hogql_queries.adapters.base import ExternalConfig, QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.self_managed import SelfManagedAdapter
from products.marketing_analytics.backend.hogql_queries.utils import map_url_to_provider

logger = structlog.get_logger(__name__)


class TestMappingSerializer(serializers.Serializer):
    table_id = serializers.UUIDField()
    source_map = serializers.DictField(child=serializers.CharField(allow_null=True, allow_blank=True))


class MarketingAnalyticsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(methods=["POST"], detail=False, url_path="test_mapping")
    def test_mapping(self, request: Request, *args, **kwargs) -> Response:
        serializer = TestMappingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        table_id = serializer.validated_data["table_id"]
        source_map_data = serializer.validated_data["source_map"]

        try:
            table = DataWarehouseTable.objects.get(id=table_id, team=self.team)
        except DataWarehouseTable.DoesNotExist:
            return Response({"success": False, "error": "Table not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            source_type = _detect_source_type(table)
            source_map = SourceMap(**{k: v for k, v in source_map_data.items() if v})
            base_currency = getattr(self.team, "base_currency", DEFAULT_CURRENCY) or DEFAULT_CURRENCY

            context = QueryContext(
                date_range=None,
                team=self.team,
                base_currency=base_currency,
            )

            adapter_class = _get_adapter_class(source_type)
            config = ExternalConfig(
                table=table,
                source_map=source_map,
                source_type=source_type,
                source_id=str(table.id),
                schema_name="test_mapping",
            )

            adapter = adapter_class(config=config, context=context)

            # Call _build_select_columns() directly (not build_query()) so field
            # resolution errors propagate to the caller instead of being swallowed.
            select_columns = adapter._build_select_columns()
            from_expr = adapter._get_from()
            where_conditions = adapter._get_where_conditions()
            where_expr = None
            if where_conditions:
                where_expr = ast.And(exprs=where_conditions) if len(where_conditions) > 1 else where_conditions[0]

            query = ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr)

            query.limit = ast.Constant(value=10)

            hogql_str = query.to_hogql()

            result = execute_hogql_query(hogql_str, self.team)

            return Response(
                {
                    "success": True,
                    "row_count": len(result.results) if result.results else 0,
                    "columns": result.columns or [],
                    "sample_data": (result.results or [])[:10],
                    "hogql": hogql_str,
                }
            )

        except Exception as e:
            logger.exception("Test mapping failed", error=str(e))
            return Response(
                {"success": False, "error": "Failed to test mapping. Check server logs for details."},
                status=status.HTTP_400_BAD_REQUEST,
            )


def _detect_source_type(table: DataWarehouseTable) -> str:
    if hasattr(table, "external_data_source") and table.external_data_source:
        return table.external_data_source.source_type or "BigQuery"

    platform = map_url_to_provider(table.url_pattern)
    return platform if platform != "BlushingHog" else "self_managed"


def _get_adapter_class(source_type: str) -> type:
    adapter_class = MarketingSourceFactory._adapter_registry.get(source_type)
    if adapter_class:
        return adapter_class

    return SelfManagedAdapter
