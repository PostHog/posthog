"""URL routes for social_signals.

Real wiring lives in ``posthog/api/__init__.py`` (nested router under projects)
and ``posthog/urls.py`` (top-level webhook). This DefaultRouter is kept as a
quick reference of the registered viewsets and is not imported anywhere.
"""

from rest_framework.routers import DefaultRouter

from .views import MentionSourceViewSet, MentionViewSet

router = DefaultRouter()
router.register(r"social_signals/mentions", MentionViewSet, basename="social_signals_mentions")
router.register(r"social_signals/sources", MentionSourceViewSet, basename="social_signals_sources")

urlpatterns = router.urls
