from rest_framework.routers import DefaultRouter

from .views import IncidentViewSet, MonitorViewSet

router = DefaultRouter()
router.register(r"monitors", MonitorViewSet, basename="monitors")
router.register(r"incidents", IncidentViewSet, basename="incidents")
urlpatterns = router.urls
