from posthog.api.routing import RouterRegistry

from products.messaging.backend.api.message_categories import MessageCategoryViewSet
from products.messaging.backend.api.message_preferences import MessagePreferencesViewSet
from products.messaging.backend.api.message_suppression import MessageSuppressionViewSet
from products.messaging.backend.api.message_templates import MessageTemplatesViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(
        r"messaging_templates", MessageTemplatesViewSet, "project_messaging_templates", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"messaging_categories", MessageCategoryViewSet, "project_messaging_categories", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"messaging_preferences", MessagePreferencesViewSet, "project_messaging_preferences", ["team_id"]
    )
    # New endpoint — register under /api/projects/ only, not the dual-route legacy shim.
    routers.projects.register(
        r"messaging_suppressions", MessageSuppressionViewSet, "project_messaging_suppressions", ["team_id"]
    )
