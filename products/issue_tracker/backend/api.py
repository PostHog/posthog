from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission
from .models import Issue
from .serializers import IssueSerializer
from .temporal.client import execute_issue_processing_workflow


class IssueViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = IssueSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    required_scopes = ["issue:read"]
    scope_object = "issue"
    queryset = Issue.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("position")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        serializer.save(team=self.team)

    def perform_update(self, serializer):
        import logging

        logger = logging.getLogger(__name__)

        # Get the current issue state before update
        issue = serializer.instance
        previous_status = issue.status

        logger.info(f"perform_update called for issue {issue.id} with validated_data: {serializer.validated_data}")

        # Save the changes
        serializer.save()

        # Check if status changed and trigger workflow
        new_status = serializer.validated_data.get("status", previous_status)
        if new_status != previous_status:
            logger.info(f"Issue {issue.id} status changed from {previous_status} to {new_status}")

            try:
                logger.info(f"Attempting to trigger workflow for issue {issue.id}")
                execute_issue_processing_workflow(
                    issue_id=str(issue.id),
                    team_id=issue.team_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    user_id=getattr(self.request.user, "id", None),
                )
                logger.info(f"Workflow trigger completed for issue {issue.id}")
            except Exception as e:
                logger.exception(f"Failed to trigger issue processing workflow for issue {issue.id}: {e}")
                import traceback

                logger.exception(f"Workflow error traceback: {traceback.format_exc()}")
        else:
            logger.info(f"Issue {issue.id} updated but status unchanged ({previous_status})")

    @action(detail=True, methods=["patch"])
    def update_status(self, request, pk=None):
        import logging

        logger = logging.getLogger(__name__)

        logger.info(f"update_status called for issue {pk} with data: {request.data}")

        issue = self.get_object()
        new_status = request.data.get("status")

        logger.info(f"Issue {issue.id}: current_status={issue.status}, new_status={new_status}")

        if new_status and new_status in Issue.Status.values:
            previous_status = issue.status
            issue.status = new_status
            issue.save()

            logger.info(f"Issue {issue.id} status updated from {previous_status} to {new_status}")

            # Trigger Temporal workflow for background processing
            try:
                logger.info(f"Attempting to trigger workflow for issue {issue.id}")
                execute_issue_processing_workflow(
                    issue_id=str(issue.id),
                    team_id=issue.team_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    user_id=getattr(request.user, "id", None),
                )
                logger.info(f"Workflow trigger completed for issue {issue.id}")
            except Exception as e:
                # Log the error but don't fail the status update
                logger.exception(f"Failed to trigger issue processing workflow for issue {issue.id}: {e}")
                import traceback

                logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

            return Response(IssueSerializer(issue).data)
        else:
            logger.warning(f"Invalid status '{new_status}' for issue {pk}. Valid statuses: {Issue.Status.values}")
        return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["patch"])
    def update_position(self, request, pk=None):
        issue = self.get_object()
        new_position = request.data.get("position")
        if new_position is not None:
            issue.position = new_position
            issue.save()
            return Response(IssueSerializer(issue).data)
        return Response({"error": "Position is required"}, status=status.HTTP_400_BAD_REQUEST)
