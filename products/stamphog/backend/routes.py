"""Route registration for stamphog. Auto-discovered by posthog/api/__init__.py."""

from posthog.api.routing import RouterRegistry

from .presentation.views import ReviewRunViewSet, StamphogRepoConfigViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"stamphog/repo_configs", StamphogRepoConfigViewSet, "project_stamphog_repo_configs", ["team_id"]
    )
    routers.projects.register(r"stamphog/review_runs", ReviewRunViewSet, "project_stamphog_review_runs", ["team_id"])
