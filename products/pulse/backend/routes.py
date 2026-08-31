from posthog.api.routing import RouterRegistry


def register_routes(routers: RouterRegistry) -> None:
    """Keep the legacy app installed for migrations without exposing HTTP endpoints."""
