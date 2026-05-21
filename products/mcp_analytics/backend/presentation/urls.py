"""URL routes for mcp_analytics."""

from rest_framework.routers import DefaultRouter

from .views import MCPFeedbackViewSet, MCPIntentClusterViewSet, MCPMissingCapabilityViewSet, MCPSessionViewSet

router = DefaultRouter()
router.register(r"feedback", MCPFeedbackViewSet, basename="mcp-analytics-feedback")
router.register(r"missing_capabilities", MCPMissingCapabilityViewSet, basename="mcp-analytics-missing-capability")
router.register(r"sessions", MCPSessionViewSet, basename="mcp-analytics-sessions")
router.register(r"intent_clusters", MCPIntentClusterViewSet, basename="mcp-analytics-intent-clusters")
urlpatterns = router.urls
