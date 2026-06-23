from posthog.api.routing import RouterRegistry

from products.surveys.backend.api.survey import SurveyViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"surveys", SurveyViewSet, "project_surveys", ["project_id"])
