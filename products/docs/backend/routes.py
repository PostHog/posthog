from posthog.api.routing import RouterRegistry

from products.docs.backend.presentation import views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"docs", views.DocViewSet, "project_docs", ["team_id"])
