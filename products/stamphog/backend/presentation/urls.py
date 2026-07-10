"""URL routes for stamphog."""

from rest_framework.routers import DefaultRouter

from .views import ReviewRunViewSet, StamphogRepoConfigViewSet

router = DefaultRouter()
router.register(r"repo_configs", StamphogRepoConfigViewSet, basename="repo_configs")
router.register(r"review_runs", ReviewRunViewSet, basename="review_runs")
urlpatterns = router.urls
