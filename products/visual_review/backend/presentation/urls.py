"""URL routes for visual_review."""

from rest_framework.routers import DefaultRouter

from .views import RepoViewSet, RunViewSet

router = DefaultRouter()
router.register(r"visual_review/repos", RepoViewSet, basename="visual_review_repos")
router.register(r"visual_review/runs", RunViewSet, basename="visual_review_runs")

urlpatterns = router.urls
