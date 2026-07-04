from posthog.api.routing import RouterRegistry

from products.pulse.backend.api.brief import BriefConfigViewSet, ProductBriefViewSet
from products.pulse.backend.api.opportunity import OpportunityViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"pulse/brief_configs", BriefConfigViewSet, "project_pulse_brief_configs", ["team_id"])
    routers.projects.register(r"pulse/briefs", ProductBriefViewSet, "project_pulse_briefs", ["team_id"])
    routers.projects.register(r"pulse/opportunities", OpportunityViewSet, "project_pulse_opportunities", ["team_id"])
