"""URL routes for engineering_analytics.

Reference router for documentation. The real wiring lives in
``posthog/api/__init__.py`` (the nested project router).
"""

from rest_framework.routers import DefaultRouter

from .views import EngineeringAnalyticsViewSet

router = DefaultRouter()
router.register(r"engineering_analytics", EngineeringAnalyticsViewSet, basename="engineering_analytics")

urlpatterns = router.urls
