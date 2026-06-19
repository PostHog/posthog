from posthog.api.routing import RouterRegistry

from products.user_interviews.backend.presentation.views import (
    IntervieweeContextViewSet,
    UserInterviewTopicViewSet,
    UserInterviewViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"user_interviews", UserInterviewViewSet, "project_user_interviews", ["team_id"])
    project_user_interview_topics_router, user_interview_topics_router = routers.register_legacy_dual_route(
        r"user_interview_topics", UserInterviewTopicViewSet, "project_user_interview_topics", ["team_id"]
    )
    user_interview_topics_router.register(
        r"interviewees",
        IntervieweeContextViewSet,
        "environment_user_interview_topic_interviewees",
        ["team_id", "topic_id"],
    )
    project_user_interview_topics_router.register(
        r"interviewees",
        IntervieweeContextViewSet,
        "project_user_interview_topic_interviewees",
        ["team_id", "topic_id"],
    )
