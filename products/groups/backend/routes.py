from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE

from products.groups.backend.presentation.views import GroupsTypesViewSet, GroupsViewSet, GroupUsageMetricViewSet


def register_routes(routers: RouterRegistry) -> None:
    # The groups API is part of the enterprise edition, so a non-EE install serves none of these routes.
    if not EE_AVAILABLE:
        return

    routers.projects.register(r"groups", GroupsViewSet, "project_groups", ["team_id"])
    group_types_router = routers.projects.register(
        r"groups_types", GroupsTypesViewSet, "project_groups_types", ["project_id"]
    )
    group_types_router.register(
        r"metrics", GroupUsageMetricViewSet, "project_groups_metrics", ["project_id", "group_type_index"]
    )
