from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE


def register_routes(routers: RouterRegistry) -> None:
    # The subscriptions API is part of the enterprise edition, so a non-EE install serves none of these routes.
    if not EE_AVAILABLE:
        return

    from products.subscriptions.backend.presentation.views import (  # noqa: PLC0415 — the views import ee/, which a non-EE install does not ship
        SubscriptionDeliveryViewSet,
        SubscriptionViewSet,
    )

    subscriptions_router = routers.projects.register(
        r"subscriptions", SubscriptionViewSet, "project_subscriptions", ["team_id"]
    )
    subscriptions_router.register(
        r"deliveries",
        SubscriptionDeliveryViewSet,
        "project_subscription_deliveries",
        ["team_id", "subscription_id"],
    )
