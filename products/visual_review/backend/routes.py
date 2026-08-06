from posthog.api.routing import RouterRegistry

from products.visual_review.backend.presentation.views import RepoRunsViewSet, RepoViewSet, RunViewSet, SnapshotViewSet


def register_routes(routers: RouterRegistry) -> None:
    visual_review_repos_router = routers.projects.register(
        r"visual_review/repos", RepoViewSet, "project_visual_review_repos", ["project_id"]
    )
    visual_review_repos_router.register(
        r"snapshots", SnapshotViewSet, "project_visual_review_snapshots", ["project_id", "repo_id"]
    )
    visual_review_repos_router.register(
        r"runs", RepoRunsViewSet, "project_visual_review_repo_runs", ["project_id", "repo_id"]
    )
    routers.projects.register(r"visual_review/runs", RunViewSet, "project_visual_review_runs", ["project_id"])
