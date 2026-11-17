"""Route registration for stamphog. Auto-discovered by posthog/api/__init__.py."""

from django.urls import URLPattern

from posthog.api.routing import RouterRegistry
from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.utils import opt_slash_path

from .presentation.views import PullRequestViewSet, ReviewRunViewSet, RoutingRunViewSet, StamphogRepoConfigViewSet

# Stamphog runs on its own GitHub App, with its own signing secret and its own consumers, so it
# gets its own view rather than sharing the customer-facing App's endpoint.
webhook_urlpatterns: list[URLPattern] = [
    opt_slash_path("github", build_webhook_view(build_github_provider("stamphog"))),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"code_review/approvals/repositories",
        StamphogRepoConfigViewSet,
        "project_code_review_approval_repositories",
        ["team_id"],
    )
    routers.projects.register(
        r"code_review/approvals/pull_requests",
        PullRequestViewSet,
        "project_code_review_approval_pull_requests",
        ["team_id"],
    )
    routers.projects.register(
        r"code_review/approvals/runs", ReviewRunViewSet, "project_code_review_approval_runs", ["team_id"]
    )
    routers.projects.register(
        r"code_review/approvals/reviewer_routing",
        RoutingRunViewSet,
        "project_code_review_approval_reviewer_routing",
        ["team_id"],
    )
