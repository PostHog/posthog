from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission
from .models import Issue, GitHubIntegration, IssueProgress
from .serializers import IssueSerializer, GitHubIntegrationSerializer
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

    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None, **kwargs):
        """Get the latest progress for an issue's Claude Code execution."""
        issue = self.get_object()
        try:
            # Get the most recent progress record for this issue
            progress = IssueProgress.objects.filter(
                issue=issue,
                team=self.team
            ).order_by('-created_at').first()
            
            if not progress:
                return Response({
                    "has_progress": False,
                    "message": "No execution progress found for this issue"
                })
            
            return Response({
                "has_progress": True,
                "id": progress.id,
                "status": progress.status,
                "current_step": progress.current_step,
                "completed_steps": progress.completed_steps,
                "total_steps": progress.total_steps,
                "progress_percentage": progress.progress_percentage,
                "output_log": progress.output_log,
                "error_message": progress.error_message,
                "created_at": progress.created_at,
                "updated_at": progress.updated_at,
                "completed_at": progress.completed_at,
                "workflow_id": progress.workflow_id,
                "workflow_run_id": progress.workflow_run_id
            })
            
        except Exception as e:
            return Response({
                "error": f"Failed to fetch progress: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["get"])
    def progress_stream(self, request, pk=None, **kwargs):
        """Get real-time progress updates (polling endpoint)."""
        issue = self.get_object()
        since = request.query_params.get('since')  # Timestamp to get updates since
        
        try:
            queryset = IssueProgress.objects.filter(
                issue=issue,
                team=self.team
            ).order_by('-created_at')
            
            if since:
                from django.utils.dateparse import parse_datetime
                since_dt = parse_datetime(since)
                if since_dt:
                    queryset = queryset.filter(updated_at__gt=since_dt)
            
            progress_records = queryset[:5]  # Limit to 5 most recent
            
            return Response({
                "progress_updates": [
                    {
                        "id": p.id,
                        "status": p.status,
                        "current_step": p.current_step,
                        "completed_steps": p.completed_steps,
                        "total_steps": p.total_steps,
                        "progress_percentage": p.progress_percentage,
                        "output_log": p.output_log,
                        "error_message": p.error_message,
                        "updated_at": p.updated_at,
                        "workflow_id": p.workflow_id
                    } for p in progress_records
                ],
                "server_time": timezone.now().isoformat()
            })
            
        except Exception as e:
            return Response({
                "error": f"Failed to fetch progress stream: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GitHubIntegrationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = GitHubIntegrationSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    required_scopes = ["issue:read"]
    scope_object = "issue"
    
    queryset = GitHubIntegration.objects.all()
    
    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)
    
    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}
    
    def perform_create(self, serializer):
        serializer.save(team=self.team)
    
    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None, **kwargs):
        """Test GitHub integration connection and permissions."""
        import logging
        logger = logging.getLogger(__name__)
        
        integration = self.get_object()
        
        if not integration.github_token:
            return Response(
                {"success": False, "error": "No GitHub token configured"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Import GitHub client
            from .temporal.github_client import GitHubClient
            import asyncio
            
            client = GitHubClient(
                token=integration.github_token,
                repo_owner=integration.repo_owner,
                repo_name=integration.repo_name
            )
            
            # Test repository access
            async def test_repo_access():
                repo_info = await client.get_repository_info()
                return repo_info
            
            # Run async test
            repo_result = asyncio.run(test_repo_access())
            
            if repo_result["success"]:
                logger.info(f"GitHub connection test successful for {integration.repo_full_name}")
                return Response({
                    "success": True,
                    "message": f"Successfully connected to {integration.repo_full_name}",
                    "repository": {
                        "name": repo_result["repo_full_name"],
                        "default_branch": repo_result["default_branch"],
                        "private": repo_result["private"],
                        "url": repo_result["html_url"]
                    }
                })
            else:
                logger.error(f"GitHub connection test failed: {repo_result['error']}")
                return Response({
                    "success": False,
                    "error": repo_result["error"]
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"GitHub connection test error: {str(e)}")
            return Response({
                "success": False,
                "error": f"Connection test failed: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=["get"])
    def status(self, request, **kwargs):
        """Get GitHub integration status for the team."""
        try:
            integration = GitHubIntegration.objects.get(team=self.team)
            return Response({
                "configured": True,
                "active": integration.is_active,
                "repository": integration.repo_full_name if integration.repo_owner and integration.repo_name else None,
                "has_token": bool(integration.github_token),
                "auto_create_pr": integration.auto_create_pr
            })
        except GitHubIntegration.DoesNotExist:
            return Response({
                "configured": False,
                "active": False,
                "repository": None,
                "has_token": False,
                "auto_create_pr": False
            })
