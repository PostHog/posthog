from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r"issues", api.IssueViewSet, basename="issue")
router.register(r"github-integration", api.GitHubIntegrationViewSet, basename="github-integration")

urlpatterns = router.urls
