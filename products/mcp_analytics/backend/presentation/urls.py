"""URL routes for mcp_analytics."""

from rest_framework.routers import DefaultRouter

from .views import MCPFeedbackViewSet, MCPMissingCapabilityViewSet

router = DefaultRouter()
router.register(r"feedback", MCPFeedbackViewSet, basename="mcp-analytics-feedback")
router.register(r"missing_capabilities", MCPMissingCapabilityViewSet, basename="mcp-analytics-missing-capability")
urlpatterns = router.urls
