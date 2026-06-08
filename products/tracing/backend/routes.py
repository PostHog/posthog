from posthog.api.routing import RouterRegistry

from products.tracing.backend.presentation.views import SpansViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(
        r"tracing/spans",
        SpansViewSet,
        "project_tracing_spans",
        ["team_id"],
    )
