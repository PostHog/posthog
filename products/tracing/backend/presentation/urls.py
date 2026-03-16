"""URL routes for tracing."""

from rest_framework.routers import DefaultRouter

from .views import SpansViewSet

router = DefaultRouter()
router.register(r"spans", SpansViewSet, basename="tracing-spans")
urlpatterns = router.urls
