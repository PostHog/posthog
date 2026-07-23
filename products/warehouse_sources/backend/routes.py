from posthog.api.routing import RouterRegistry

from products.warehouse_sources.backend.presentation.views import external_data_schema, external_data_source


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"external_data_sources",
        external_data_source.ExternalDataSourceViewSet,
        "project_external_data_sources",
        ["team_id"],
    )
    routers.projects.register(
        r"external_data_schemas",
        external_data_schema.ExternalDataSchemaViewset,
        "project_external_data_schemas",
        ["team_id"],
    )
