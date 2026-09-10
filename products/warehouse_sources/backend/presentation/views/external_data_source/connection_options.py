"""Serializers and endpoints for source connection options."""

from __future__ import annotations

from typing import Any, cast

from django.db.models import Q

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.direct_sql.capability import direct_capable_source_types

from posthog.api.utils import action
from posthog.models.user import User
from posthog.permissions import is_service_auth

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.data_warehouse.backend.facade.models import ExternalDataSourceRevenueAnalyticsConfig
from products.revenue_analytics.backend.facade.api import remove_person_join
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ExternalDataDestination,
    ExternalDataSchema,
    ExternalDataSource,
    ExternalDataSourceDestination,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.destination_links import (
    DestinationLinkSerializer,
    SourceDestinationsSerializer,
    set_source_destinations,
)
from products.warehouse_sources.backend.presentation.views.public_source_configs import build_source_configs

from . import helpers, viewset


class ExternalDataSourceRevenueAnalyticsConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSourceRevenueAnalyticsConfig
        fields = ["enabled", "include_invoiceless_charges"]


class ExternalDataSourceConnectionMetadataSerializer(serializers.Serializer):
    database = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database name discovered for a direct connection.",
    )
    version = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database version string reported by the direct connection.",
    )
    engine = serializers.ChoiceField(
        read_only=True,
        required=False,
        allow_null=True,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    function_source = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="System catalog or function source used to discover supported functions.",
    )
    available_functions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        required=False,
        help_text="Functions discovered as available on the direct connection.",
    )


class ExternalDataSourceConnectionOptionSerializer(serializers.ModelSerializer):
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        read_only=True,
        help_text="The source type (e.g. 'Postgres', 'MySQL', 'Snowflake').",
    )
    access_method = serializers.ChoiceField(
        choices=ExternalDataSource.AccessMethod.choices,
        read_only=True,
        help_text="'direct' for pure live-query sources; 'warehouse' for synced sources with direct query enabled.",
    )
    supports_hogql = serializers.SerializerMethodField(
        help_text="Whether HogQL queries compile for this connection. When false, only raw SQL (sendRawQuery) works.",
    )
    is_builtin_managed_warehouse = serializers.SerializerMethodField(
        help_text="Whether this option is the built-in PostHog managed warehouse connection.",
    )
    description = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="User-set description of the source, shown as its display name in the connection picker when set.",
    )

    @extend_schema_field(serializers.BooleanField())
    def get_supports_hogql(self, source: ExternalDataSource) -> bool:
        # Function-local: keeps the direct-SQL driver imports off the django.setup() path.
        from posthog.hogql.direct_sql.capability import direct_supports_hogql  # noqa: PLC0415

        return direct_supports_hogql(source)

    @extend_schema_field(serializers.BooleanField())
    def get_is_builtin_managed_warehouse(self, source: ExternalDataSource) -> bool:
        return source.pk == self.context.get("builtin_managed_warehouse_source_id")

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "prefix",
            "engine",
            "source_type",
            "access_method",
            "supports_hogql",
            "is_builtin_managed_warehouse",
            "description",
        ]
        read_only_fields = fields


class DirectConnectionSourceOptionSerializer(serializers.Serializer):
    """A source type that can be added as a direct (live-query) connection, with display metadata."""

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        read_only=True,
        help_text="The source type to start a direct-connection setup for (e.g. 'Postgres', 'ClickHouse').",
    )
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        read_only=True,
        help_text="Human-readable name to show in the picker (falls back to the source type).",
    )
    icon_path = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Path to the source's icon asset, or null when the source ships no icon.",
    )


class ExternalDataSourceConnectionOptionsMixin:
    @extend_schema(responses=ExternalDataSourceConnectionOptionSerializer(many=True))
    @action(
        methods=["GET"],
        detail=False,
        pagination_class=None,
        filter_backends=[],
        required_scopes=["external_data_source:read"],
    )
    def connections(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        connection_sources = (
            ExternalDataSource._base_manager.filter(
                team_id=self.team_id,
                source_type__in=direct_capable_source_types(),
            )
            # Pure-direct sources are always live; synced sources only when the toggle is on.
            .filter(Q(access_method=ExternalDataSource.AccessMethod.DIRECT) | Q(direct_query_enabled=True))
            .exclude(deleted=True)
            .only(
                "id",
                "prefix",
                "description",
                "connection_metadata",
                "source_type",
                "access_method",
            )
            .order_by(self.ordering)
        )
        managed_candidates = connection_sources.filter(ExternalDataSource.ready_managed_warehouse_q()).only(
            "id",
            "team_id",
            "prefix",
            "description",
            "connection_metadata",
            "source_type",
            "access_method",
            "direct_query_enabled",
            "job_inputs",
        )
        managed_source = next(
            (source for source in managed_candidates if source.is_dynamic_managed_warehouse),
            None,
        ) or next((source for source in managed_candidates if source.is_managed_warehouse_ready), None)
        if managed_source is not None:
            external_sources = connection_sources.exclude(prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        else:
            canonical_source = helpers._canonical_legacy_managed_warehouse_source(connection_sources)
            external_sources = helpers._hide_noncanonical_managed_warehouse_sources(
                connection_sources, canonical_source
            )
        if is_service_auth(request):
            accessible_external_sources = external_sources
        else:
            accessible_external_sources = self.user_access_control.filter_queryset_by_access_level(external_sources)
            if not self.user_access_control.has_resource_access(
                "external_data_source"
            ) and not self.user_access_control.has_any_specific_access_for_resource(
                "external_data_source", required_level="viewer"
            ):
                accessible_external_sources = accessible_external_sources.filter(created_by=cast(User, request.user))
        accessible_sources = list(accessible_external_sources)
        options = ([managed_source] if managed_source is not None else []) + accessible_sources

        serializer = ExternalDataSourceConnectionOptionSerializer(
            options,
            many=True,
            context={"builtin_managed_warehouse_source_id": managed_source.pk if managed_source is not None else None},
        )
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @extend_schema(responses=DirectConnectionSourceOptionSerializer(many=True))
    @action(methods=["GET"], detail=False, pagination_class=None, filter_backends=[])
    def direct_connection_options(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Source types the user can add as a direct connection, driven by the direct-SQL capability
        surface so the picker never drifts from the engines we actually support."""
        direct_types = direct_capable_source_types()
        options = [
            {
                "source_type": source_type,
                "label": config.get("label") or source_type,
                "icon_path": config.get("iconPath"),
            }
            for source_type, config in build_source_configs(include_tables=False).items()
            if source_type in direct_types
        ]
        options.sort(key=lambda option: str(option["label"]).lower())

        serializer = DirectConnectionSourceOptionSerializer(options, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @extend_schema(
        request=DestinationLinkSerializer,
        responses={200: SourceDestinationsSerializer},
    )
    @action(methods=["GET", "PATCH"], detail=True)
    def destinations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read or replace the destinations every table on this source syncs to.

        A table with its own override ignores this set until the override is cleared.
        """
        source = self.get_object()

        if request.method == "GET":
            attached = [
                str(link.destination_id)
                for link in ExternalDataSourceDestination.objects.for_team(self.team_id)
                .filter(source_id=source.id, enabled=True)
                .exclude(destination__deleted=True)
            ]
            # A source nobody configured has no links but is not syncing nowhere: it syncs to the
            # PostHog warehouse. Report where it actually goes, or the picker shows every
            # destination off and saving from that state silently drops the warehouse.
            # Looked up rather than resolved, because `resolve_destinations` creates the
            # warehouse row on demand and a GET must not write.
            if not attached:
                warehouse = (
                    ExternalDataDestination.objects.for_team(self.team_id)
                    .filter(type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE, deleted=False)
                    .first()
                )
                attached = [str(warehouse.id)] if warehouse else []
            return Response(
                status=status.HTTP_200_OK, data=SourceDestinationsSerializer({"destination_ids": attached}).data
            )

        serializer = DestinationLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Editor on the source isn't enough on its own: this replaces the destination set every
        # table without its own override inherits, and (like `destroy`) never resolves a schema
        # through DRF's object permissions, so a table locked below the source would otherwise be
        # rerouted to a destination its editor never had access to.
        schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=source.id)
            .select_related("table")
        )
        self._assert_can_write_schemas(schemas)

        attached = set_source_destinations(
            team_id=self.team_id,
            source_id=source.id,
            destination_ids=serializer.validated_data["destination_ids"],
        )
        return Response(
            status=status.HTTP_200_OK, data=SourceDestinationsSerializer({"destination_ids": attached}).data
        )

    @action(methods=["PATCH"], detail=True)
    def revenue_analytics_config(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the revenue analytics configuration and return the full external data source."""
        external_data_source = self.get_object()
        config = external_data_source.revenue_analytics_config_safe

        config_serializer = ExternalDataSourceRevenueAnalyticsConfigSerializer(config, data=request.data, partial=True)
        config_serializer.is_valid(raise_exception=True)
        config_serializer.save()

        table_prefix = external_data_source.prefix or ""

        if config.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            viewset.ensure_person_join(self.team.pk, table_prefix)
        else:
            try:
                managed_viewset = DataWarehouseManagedViewSet.objects.get(
                    team=self.team,
                    kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
                )
                managed_viewset.delete_with_views()

            except DataWarehouseManagedViewSet.DoesNotExist:
                pass
            remove_person_join(self.team.pk, table_prefix)

        # Return the full external data source with updated config
        source_serializer = self.get_serializer(external_data_source, context=self.get_serializer_context())
        return Response(source_serializer.data)
