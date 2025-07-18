from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission
from .models import Issue
from .serializers import IssueSerializer


class IssueViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = IssueSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    required_scopes = ["issue:read"]
    scope_object = "issue"
    queryset = Issue.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("position", "priority")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        serializer.save(team=self.team)

    @action(detail=True, methods=["patch"])
    def update_status(self, request, pk=None):
        issue = self.get_object()
        new_status = request.data.get("status")
        if new_status and new_status in Issue.Status.values:
            issue.status = new_status
            issue.save()
            return Response(IssueSerializer(issue).data)
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
