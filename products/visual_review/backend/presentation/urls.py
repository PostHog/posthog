"""URL routes for visual_review."""

from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet, RunViewSet

router = DefaultRouter()
router.register(r"visual_review/projects", ProjectViewSet, basename="visual_review_projects")
router.register(r"visual_review/runs", RunViewSet, basename="visual_review_runs")

urlpatterns = router.urls
