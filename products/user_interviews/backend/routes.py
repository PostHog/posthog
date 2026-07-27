from posthog.api.routing import RouterRegistry

from products.user_interviews.backend.presentation.views import (
    IntervieweeContextViewSet,
    UserInterviewTopicViewSet,
    UserInterviewViewSet,
)


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
