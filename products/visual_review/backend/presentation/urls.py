"""URL routes for visual_review.

Real wiring lives in `posthog/api/__init__.py` (nested router). This flat
DefaultRouter is kept as a documentation/reference of the registered viewsets
and isn't imported anywhere; the snapshot endpoint requires nested routing
(`/repos/{repo_id}/snapshots/...`) so it's omitted here.
"""

from rest_framework.routers import DefaultRouter

from .views import RepoViewSet, RunViewSet

router = DefaultRouter()
router.register(r"visual_review/repos", RepoViewSet, basename="visual_review_repos")
router.register(r"visual_review/runs", RunViewSet, basename="visual_review_runs")

urlpatterns = router.urls
