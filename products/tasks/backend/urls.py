from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register(r"tasks", api.TaskViewSet, basename="task")
router.register(r"workflows", api.TaskWorkflowViewSet, basename="workflow")
router.register(r"workflow-stages", api.WorkflowStageViewSet, basename="workflow-stage")
router.register(r"agents", api.AgentDefinitionViewSet, basename="agent")

urlpatterns = router.urls
