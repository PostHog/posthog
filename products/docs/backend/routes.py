from posthog.api.routing import RouterRegistry

from products.docs.backend.presentation import views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"docs", views.DocViewSet, "project_docs", ["team_id"])
    routers.projects.register(r"doc_kpis", views.SpaceKpiViewSet, "project_doc_kpis", ["team_id"])
