"""URL routes for founder_mode.

Real wiring lives in `posthog/api/__init__.py` (nested router under projects).
This flat DefaultRouter is kept as a documentation/reference of the registered
viewsets and is intentionally not imported anywhere.
"""

from rest_framework.routers import DefaultRouter

from .views import FounderProjectViewSet

router = DefaultRouter()
router.register(r"founder_projects", FounderProjectViewSet, basename="founder_projects")

urlpatterns = router.urls
