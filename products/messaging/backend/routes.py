from posthog.api.routing import RouterRegistry

from products.messaging.backend.api.message_categories import MessageCategoryViewSet
from products.messaging.backend.api.message_preferences import MessagePreferencesViewSet
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
