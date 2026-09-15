from posthog.api.routing import RouterRegistry

from products.surveys.backend.api.survey import SurveyViewSet
from products.surveys.backend.presentation.desktop_feedback import DesktopFeedbackViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"desktop_feedback", DesktopFeedbackViewSet, "desktop_feedback")
    routers.projects.register(r"surveys", SurveyViewSet, "project_surveys", ["project_id"])
