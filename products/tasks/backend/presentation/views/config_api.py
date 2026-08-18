from dataclasses import asdict
from typing import cast

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.user import User
from posthog.permissions import APIScopePermission, TeamMemberStrictManagementPermission

from products.tasks.backend.facade import ai_run_defaults
from products.tasks.backend.presentation.serializers import (
    TasksAIRunPreferencesSerializer,
    TasksTeamConfigResponseSerializer,
    TasksUserConfigResponseSerializer,
)

_AUTH_CLASSES = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]


def _user_id(request: Request) -> int:
    """The requesting user's id; `IsAuthenticated` guarantees a real user on these views."""
    return cast(User, request.user).id


def _validated_triple(request: Request) -> dict:
    serializer = TasksAIRunPreferencesSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class TasksTeamConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-level tasks configuration (singleton per project).

    GET  /tasks/config/  → retrieve
    POST /tasks/config/  → update
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    # One value that decides what every unpinned run on the project launches with, so writing it is
    # admin-only; reading stays open to members, who need it to see what they're inheriting.
    permission_classes = [IsAuthenticated, APIScopePermission, TeamMemberStrictManagementPermission]
    serializer_class = TasksTeamConfigResponseSerializer

    @extend_schema(
        responses={200: TasksTeamConfigResponseSerializer},
        description="Retrieve the project-wide default AI run preferences for task runs.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response({"ai_run_preferences": ai_run_defaults.get_team_ai_run_preferences(self.team_id)})

    @extend_schema(
        request=TasksAIRunPreferencesSerializer,
        responses={200: TasksTeamConfigResponseSerializer},
        description=(
            "Set the project-wide default AI run preferences applied to task runs created "
            "without an explicit runtime selection. Send all fields as null to clear."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        triple = _validated_triple(request)
        try:
            payload = ai_run_defaults.update_team_ai_run_preferences(self.team_id, **triple)
        except DjangoValidationError as e:
            raise ValidationError(e.messages)
        return Response({"ai_run_preferences": payload})


class TasksUserConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's per-project tasks configuration.

    GET  /tasks/my_config/  → retrieve (includes the resolved effective defaults)
    POST /tasks/my_config/  → update
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [IsAuthenticated, APIScopePermission]
    serializer_class = TasksUserConfigResponseSerializer

    def _response(self, request: Request, preferences: dict) -> Response:
        resolved = ai_run_defaults.resolve_ai_run_defaults(
            self.team_id, _user_id(request), user_preferences=preferences
        )
        return Response({"ai_run_preferences": preferences, "resolved_ai_run_defaults": asdict(resolved)})

    @extend_schema(
        # `@me` is not identifier-safe, so the URL-derived default operationId is rejected.
        operation_id="tasks_me_config_list",
        responses={200: TasksUserConfigResponseSerializer},
        description=(
            "Retrieve your per-project default AI run preferences, plus the resolved defaults "
            "a new run will use when no explicit runtime selection is sent (your preference "
            "over the project default)."
        ),
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._response(request, ai_run_defaults.get_user_ai_run_preferences(self.team_id, _user_id(request)))

    @extend_schema(
        operation_id="tasks_me_config_create",
        request=TasksAIRunPreferencesSerializer,
        responses={200: TasksUserConfigResponseSerializer},
        description=(
            "Set your per-project default AI run preferences; they override the project default "
            "wholesale. Send all fields as null to clear and inherit the project default."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        triple = _validated_triple(request)
        try:
            payload = ai_run_defaults.update_user_ai_run_preferences(self.team_id, _user_id(request), **triple)
        except DjangoValidationError as e:
            raise ValidationError(e.messages)
        return self._response(request, payload)
