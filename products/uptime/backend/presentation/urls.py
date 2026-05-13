from rest_framework.routers import DefaultRouter

from .views import MonitorViewSet

router = DefaultRouter()
router.register(r"monitors", MonitorViewSet, basename="monitors")
urlpatterns = router.urls
