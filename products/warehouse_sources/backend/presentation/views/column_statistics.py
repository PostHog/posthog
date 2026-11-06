import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, WarehouseColumnStatistics


class WarehouseColumnStatisticsSerializer(serializers.ModelSerializer):
    table = serializers.UUIDField(
        source="table_id", read_only=True, help_text="ID of the data warehouse table this column belongs to."
    )
    column_name = serializers.CharField(read_only=True, help_text="Name of the column these statistics describe.")
    column_type = serializers.CharField(
        read_only=True, help_text="ClickHouse type the statistics were computed against (e.g. Int64, DateTime64)."
    )
    row_count = serializers.IntegerField(
        read_only=True, help_text="Total number of rows in the table when these statistics were computed."
    )
    null_count = serializers.IntegerField(
        read_only=True, help_text="Number of NULL values in this column, or null if the Delta log carried no count."
    )
    null_fraction = serializers.FloatField(
        read_only=True, help_text="Fraction of values that are NULL (null_count / row_count), between 0 and 1."
    )
    min_value = serializers.CharField(
        read_only=True,
        help_text=(
            "Minimum value in the column, as a string. Null when unavailable. For string columns this may be "
            "truncated by the underlying Delta statistics, so treat string bounds as approximate."
        ),
    )
    max_value = serializers.CharField(
        read_only=True, help_text="Maximum value in the column, as a string. Null when unavailable (see min_value)."
    )
    has_min_max = serializers.BooleanField(
        read_only=True,
        help_text="Whether the Delta log carried min/max statistics for this column (false for some nested/binary types).",
    )
    computed_at = serializers.DateTimeField(read_only=True, help_text="When these statistics were last computed.")
    computed_for_delta_version = serializers.IntegerField(
        read_only=True, help_text="Delta table version the statistics were computed against."
    )
    stats_basis = serializers.CharField(
        read_only=True, help_text="How the statistics were produced. Currently always 'delta_log'."
    )

    class Meta:
        model = WarehouseColumnStatistics
        fields = [
            "id",
            "table",
            "column_name",
            "column_type",
            "row_count",
            "null_count",
            "null_fraction",
            "min_value",
            "max_value",
            "has_min_max",
            "computed_at",
            "computed_for_delta_version",
            "stats_basis",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class WarehouseColumnStatisticsViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read per-column data statistics (null fraction, min/max, row count) for warehouse tables.

    Statistics are computed automatically after a sync and surfaced to the AI agent so it can write
    better queries. They are system-owned and read-only here. List can be filtered to one table with
    `?table_id=<uuid>`.
    """

    # Statistics describe `DataWarehouseTable` rows, so they live under the warehouse table family — both
    # the resource-level scope and the per-object filtering below key off `warehouse_table`.
    scope_object = "warehouse_table"
    scope_object_read_actions = ["list", "retrieve"]
    # `.unscoped()` is import-safe (the fail-closed manager raises on `.all()` without team context);
    # the mixin scopes every request by team_id via the parent lookup.
    queryset = WarehouseColumnStatistics.objects.unscoped()
    serializer_class = WarehouseColumnStatisticsSerializer
    ordering = "column_name"

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="table_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Only return statistics for this data warehouse table.",
            )
        ]
    )
    def list(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset: Any) -> Any:
        # Statistics inherit their table's access: only expose those whose table the user can reach.
        # Applied for every action so retrieve on stats for an inaccessible table 404s through the
        # queryset rather than slipping past object-level checks.
        accessible_tables = self.user_access_control.filter_queryset_by_access_level(
            DataWarehouseTable.objects.filter(team_id=self.team_id)
        )
        queryset = queryset.filter(table__in=accessible_tables)
        table_id = self.request.query_params.get("table_id")
        if table_id:
            # Guard the UUID cast: a malformed table_id would otherwise raise ValueError deep in the ORM
            # and surface as a 500. Treat an unparseable id as "no such table" (empty result).
            try:
                uuid.UUID(table_id)
            except ValueError:
                return queryset.none()
            queryset = queryset.filter(table_id=table_id)
        return queryset.order_by(self.ordering)
