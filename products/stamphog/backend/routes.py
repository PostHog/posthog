"""Route registration for stamphog. Auto-discovered by posthog/api/__init__.py."""

from django.urls import URLPattern

from posthog.api.routing import RouterRegistry
from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.utils import opt_slash_path

from .presentation.views import DigestRunViewSet, PullRequestViewSet, ReviewRunViewSet, StamphogRepoConfigViewSet

# Stamphog runs on its own GitHub App, with its own signing secret and its own consumers, so it
# gets its own view rather than sharing the customer-facing App's endpoint.
urlpatterns: list[URLPattern] = [
    opt_slash_path("webhooks/stamphog/github", build_webhook_view(build_github_provider("stamphog"))),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"stamphog/repo_configs", StamphogRepoConfigViewSet, "project_stamphog_repo_configs", ["team_id"]
    )
    routers.projects.register(
        r"stamphog/pull_requests", PullRequestViewSet, "project_stamphog_pull_requests", ["team_id"]
    )
    routers.projects.register(r"stamphog/review_runs", ReviewRunViewSet, "project_stamphog_review_runs", ["team_id"])
    routers.projects.register(r"stamphog/digest_runs", DigestRunViewSet, "project_stamphog_digest_runs", ["team_id"])
