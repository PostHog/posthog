from posthog.api.routing import RouterRegistry

from products.tracing.backend.presentation.views import SpansViewSet
from products.tracing.backend.presentation.views_api import TracingViewViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"tracing/spans",
        SpansViewSet,
        "project_tracing_spans",
        ["team_id"],
    )
    routers.projects.register(
        r"tracing/views",
        TracingViewViewSet,
        "project_tracing_views",
        ["team_id"],
    )
