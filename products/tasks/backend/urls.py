from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"tasks", api.TaskViewSet, basename="task")

urlpatterns = router.urls
