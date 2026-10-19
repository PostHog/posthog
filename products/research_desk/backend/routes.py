from posthog.api.routing import RouterRegistry

from products.research_desk.backend.presentation.views import (
    ContactCheckViewSet,
    ResearchSessionViewSet,
    ResearchSourceViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"research_desk/sources", ResearchSourceViewSet, "project_research_desk_sources", ["project_id"]
    )
    routers.projects.register(
        r"research_desk/sessions", ResearchSessionViewSet, "project_research_desk_sessions", ["project_id"]
    )
    routers.projects.register(
        r"research_desk/contact_check", ContactCheckViewSet, "project_research_desk_contact_check", ["project_id"]
    )
