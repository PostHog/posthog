from posthog.api.routing import RouterRegistry

from products.warehouse_suggestions.backend.presentation.views import WarehouseSuggestionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"warehouse_suggestions", WarehouseSuggestionViewSet, "project_warehouse_suggestions", ["team_id"]
    )
