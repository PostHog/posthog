"""Route registration for stamphog. Auto-discovered by posthog/api/__init__.py."""

from posthog.api.routing import RouterRegistry

from .presentation.views import DigestChannelViewSet, DigestRunViewSet, ReviewRunViewSet, StamphogRepoConfigViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"stamphog/repo_configs", StamphogRepoConfigViewSet, "project_stamphog_repo_configs", ["team_id"]
    )
    routers.projects.register(r"stamphog/review_runs", ReviewRunViewSet, "project_stamphog_review_runs", ["team_id"])
    routers.projects.register(
        r"stamphog/digest_channels", DigestChannelViewSet, "project_stamphog_digest_channels", ["team_id"]
    )
    routers.projects.register(r"stamphog/digest_runs", DigestRunViewSet, "project_stamphog_digest_runs", ["team_id"])
