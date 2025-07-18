from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"issues", api.IssueViewSet, basename="issue")

urlpatterns = router.urls
