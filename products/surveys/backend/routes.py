from posthog.api.routing import RouterRegistry

from products.surveys.backend.api.survey import SurveyViewSet
from products.surveys.backend.presentation.desktop_feedback import DesktopFeedbackViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"desktop_feedback", DesktopFeedbackViewSet, "project_desktop_feedback", ["team_id"])
    routers.projects.register(r"surveys", SurveyViewSet, "project_surveys", ["project_id"])
