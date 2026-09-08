from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, TeamMemberStrictManagementPermission

from products.tasks.backend.facade import ai_run_defaults, task_analysis
from products.tasks.backend.presentation.serializers import (
    TaskAnalysisRunSerializer,
    TasksAIRunPreferencesSerializer,
    TasksAnalysisConfigResponseSerializer,
)
from products.tasks.backend.presentation.views.config_api import validated_preference_triple

_AUTH_CLASSES = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]


class TasksAnalysisConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-level task-analysis configuration (singleton per project).

    GET  /tasks/analysis/config/  → retrieve
    POST /tasks/analysis/config/  → update
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    # Same gate as the project-wide run defaults: members read, admins write.
    permission_classes = [IsAuthenticated, APIScopePermission, TeamMemberStrictManagementPermission]
    serializer_class = TasksAnalysisConfigResponseSerializer

    @extend_schema(
        responses={200: TasksAnalysisConfigResponseSerializer},
        description="Retrieve the model triple task-analysis runs launch with for this project.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        preferences = ai_run_defaults.get_team_analysis_run_preferences(self.team_id)
        return Response(TasksAnalysisConfigResponseSerializer({"analysis_run_preferences": preferences}).data)

    @extend_schema(
        request=TasksAIRunPreferencesSerializer,
        responses={200: TasksAnalysisConfigResponseSerializer},
        description=(
            "Set the model triple task-analysis runs launch with for this project. "
            "Send all fields as null to return to the built-in analysis model."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        triple = validated_preference_triple(request)
        try:
            payload = ai_run_defaults.update_team_analysis_run_preferences(self.team_id, **triple)
        except DjangoValidationError as e:
            raise ValidationError(e.messages)
        return Response(TasksAnalysisConfigResponseSerializer({"analysis_run_preferences": payload}).data)


class TaskAnalysisRunsPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class TaskAnalysisRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The project's task-analysis runs, newest first.

    GET /tasks/analysis/runs/  → list
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [IsAuthenticated, APIScopePermission]
    serializer_class = TaskAnalysisRunSerializer
    pagination_class = TaskAnalysisRunsPagination

    @extend_schema(
        responses={200: TaskAnalysisRunSerializer(many=True)},
        description="List the project's task-analysis runs, newest first, with the activities each one reported.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        runs = self.paginate_queryset(task_analysis.list_task_analysis_runs(self.team_id))
        rows = [task_analysis.task_analysis_run_row(run) for run in runs or []]
        return self.get_paginated_response(TaskAnalysisRunSerializer(rows, many=True).data)
