from django.urls import URLPattern, path
from django.views.decorators.csrf import csrf_exempt

from posthog.api.routing import RouterRegistry

from products.user_interviews.backend.presentation.views import (
    IntervieweeContextViewSet,
    UserInterviewTopicViewSet,
    UserInterviewViewSet,
)
from products.user_interviews.backend.presentation.webhooks import vapi_webhook

api_urlpatterns: list[URLPattern] = [
    path(
        "vapi_webhook/",
        csrf_exempt(vapi_webhook),
        name="user_interviews_vapi_webhook",
    ),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"user_interviews", UserInterviewViewSet, "project_user_interviews", ["team_id"])
    user_interview_topics_router = routers.projects.register(
        r"user_interview_topics", UserInterviewTopicViewSet, "project_user_interview_topics", ["team_id"]
    )
    user_interview_topics_router.register(
        r"interviewees",
        IntervieweeContextViewSet,
        "project_user_interview_topic_interviewees",
        ["team_id", "topic_id"],
    )
