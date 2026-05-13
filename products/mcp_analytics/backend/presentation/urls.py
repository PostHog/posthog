"""URL routes for mcp_analytics."""

from rest_framework.routers import DefaultRouter

from .views import MCPFeedbackViewSet, MCPMissingCapabilityViewSet, MCPMissingToolsViewSet

router = DefaultRouter()
router.register(r"feedback", MCPFeedbackViewSet, basename="mcp-analytics-feedback")
router.register(r"missing_capabilities", MCPMissingCapabilityViewSet, basename="mcp-analytics-missing-capability")
router.register(r"missing_tools", MCPMissingToolsViewSet, basename="mcp-analytics-missing-tools")
urlpatterns = router.urls
