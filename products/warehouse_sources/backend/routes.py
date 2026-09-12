from posthog.api.routing import RouterRegistry

from products.warehouse_sources.backend.presentation.views import (
    column_statistics,
    external_data_destination,
    external_data_source,
)
from products.warehouse_sources.backend.presentation.views.external_data_schema.viewset import ExternalDataSchemaViewset


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"external_data_sources",
        external_data_source.ExternalDataSourceViewSet,
        "project_external_data_sources",
        ["team_id"],
    )
    routers.projects.register(
        r"external_data_destinations",
        external_data_destination.ExternalDataDestinationViewSet,
        "project_external_data_destinations",
        ["team_id"],
    )
    routers.projects.register(
        r"external_data_schemas",
        ExternalDataSchemaViewset,
        "project_external_data_schemas",
        ["team_id"],
    )
    routers.projects.register(
        r"warehouse_column_statistics",
        column_statistics.WarehouseColumnStatisticsViewSet,
        "project_warehouse_column_statistics",
        ["team_id"],
    )
