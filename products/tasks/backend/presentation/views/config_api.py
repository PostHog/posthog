from dataclasses import asdict
from typing import cast

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.user import User
from posthog.permissions import APIScopePermission, TeamMemberStrictManagementPermission

from products.tasks.backend.facade import (
    ai_run_defaults,
    task_defaults as task_defaults_store,
)
from products.tasks.backend.facade.agent_instructions import AgentInstructionsStore
from products.tasks.backend.facade.client_provenance import is_sandbox_oauth_request
from products.tasks.backend.facade.run_config import get_model_access_error
from products.tasks.backend.presentation.serializers import (
    TasksAgentInstructionsSerializer,
    TasksAIRunPreferencesSerializer,
    TasksTaskDefaultsSerializer,
    TasksTaskDefaultsUpdateSerializer,
    TasksTeamConfigResponseSerializer,
    TasksUserConfigResponseSerializer,
)

_AUTH_CLASSES: list[type[BaseAuthentication]] = [
    SessionAuthentication,
    PersonalAPIKeyAuthentication,
    OAuthAccessTokenAuthentication,
]


class DenySandboxAgentInstructionWrites(BasePermission):
    """A run must not rewrite the instructions every later run loads, or one injected prompt persists."""

    message = "Task agents cannot modify agent instructions."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS or getattr(view, "action", None) != "agent_instructions":
            return True
        return not is_sandbox_oauth_request(request)


class DenySandboxTaskDefaultsWrites(BasePermission):
    """A run must not change how later tasks start, for example to open pull requests on its own."""

    message = "Task agents cannot modify task defaults."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS or getattr(view, "action", None) != "task_defaults":
            return True
        return not is_sandbox_oauth_request(request)


class _SingletonSchema(PostHogAutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array.

    The config is one object per person and project, not a collection.
    """

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


def _user_id(request: Request) -> int:
    """The requesting user's id; `IsAuthenticated` guarantees a real user on these views."""
    return cast(User, request.user).id


def _validated_preferences(request: Request) -> dict:
    serializer = TasksAIRunPreferencesSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    preferences = serializer.validated_data
    # Storing a flag-gated model the writer isn't entitled to would only ever
    # produce runs the resolver skips or the run paths refuse — reject it here
    # so the settings page says so immediately. Resolution re-checks per acting
    # user, which also covers entitlements that change after the write.
    error = get_model_access_error(preferences.get("model"), distinct_id=cast(User, request.user).distinct_id)
    if error is not None:
        raise ValidationError({"model": error})
    return preferences


def _validated_agent_instructions(request: Request) -> str:
    serializer = TasksAgentInstructionsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["agent_instructions"]


class TasksTeamConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-level tasks configuration (singleton per project).

    GET  /tasks/config/  → retrieve
    POST /tasks/config/  → update
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    # One value that decides what every unpinned run on the project launches with, so writing it is
    # admin-only; reading stays open to members, who need it to see what they're inheriting.
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        TeamMemberStrictManagementPermission,
        DenySandboxAgentInstructionWrites,
    ]
    serializer_class = TasksTeamConfigResponseSerializer

    @extend_schema(
        responses={200: TasksTeamConfigResponseSerializer},
        description="Retrieve the project-wide default AI run preferences for task runs.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        preferences = ai_run_defaults.get_team_ai_run_preferences(self.team_id)
        return self._response(preferences)

    def _response(self, preferences: dict) -> Response:
        return Response(
            TasksTeamConfigResponseSerializer(
                {
                    "ai_run_preferences": preferences,
                    "agent_instructions": AgentInstructionsStore().get_project(self.team_id),
                }
            ).data
        )

    @extend_schema(
        request=TasksAIRunPreferencesSerializer,
        responses={200: TasksTeamConfigResponseSerializer},
        description=(
            "Set the project-wide default AI run preferences applied to task runs created "
            "without an explicit runtime selection. Send all fields as null to clear."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        preferences = _validated_preferences(request)
        try:
            payload = ai_run_defaults.update_team_ai_run_preferences(self.team_id, **preferences)
        except DjangoValidationError as e:
            raise ValidationError(e.messages)
        return self._response(payload)

    @extend_schema(
        request=TasksAgentInstructionsSerializer,
        responses={200: TasksAgentInstructionsSerializer},
        description=(
            "Set the project instructions that PostHog cloud agents load as their user-level AGENTS.md in every "
            "eligible Tasks run, including autonomous runs. Send an empty string to clear."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="agent_instructions", required_scopes=["task:write"])
    def agent_instructions(self, request: Request, *args, **kwargs) -> Response:
        instructions = AgentInstructionsStore().set_project(self.team_id, _validated_agent_instructions(request))
        return Response(TasksAgentInstructionsSerializer({"agent_instructions": instructions}).data)


class TasksUserConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's per-project tasks configuration.

    GET  /tasks/my_config/  → retrieve (includes the resolved effective defaults)
    POST /tasks/my_config/  → update
    """

    schema = _SingletonSchema()
    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        DenySandboxAgentInstructionWrites,
        DenySandboxTaskDefaultsWrites,
    ]
    serializer_class = TasksUserConfigResponseSerializer

    def _response(self, request: Request, preferences: dict) -> Response:
        resolved = ai_run_defaults.resolve_ai_run_defaults(
            self.team_id, _user_id(request), user_preferences=preferences
        )
        return Response(
            TasksUserConfigResponseSerializer(
                {
                    "ai_run_preferences": preferences,
                    "resolved_ai_run_defaults": asdict(resolved),
                    "agent_instructions": AgentInstructionsStore().get_personal(self.team_id, _user_id(request)),
                    "task_defaults": task_defaults_store.get_user_task_defaults(self.team_id, _user_id(request)),
                }
            ).data
        )

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
        preferences = _validated_preferences(request)
        try:
            payload = ai_run_defaults.update_user_ai_run_preferences(self.team_id, _user_id(request), **preferences)
        except DjangoValidationError as e:
            raise ValidationError(e.messages)
        return self._response(request, payload)

    @extend_schema(
        operation_id="tasks_me_config_agent_instructions_create",
        request=TasksAgentInstructionsSerializer,
        responses={200: TasksAgentInstructionsSerializer},
        description=(
            "Set your personal instructions, which PostHog cloud agents load in Tasks runs you start, after the "
            "project instructions. Autonomous runs never get them. Anyone who continues a task you started can "
            "see them, so leave out anything private. Send an empty string to clear."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="agent_instructions", required_scopes=["task:write"])
    def agent_instructions(self, request: Request, *args, **kwargs) -> Response:
        instructions = AgentInstructionsStore().set_personal(
            self.team_id, _user_id(request), _validated_agent_instructions(request)
        )
        return Response(TasksAgentInstructionsSerializer({"agent_instructions": instructions}).data)

    @extend_schema(
        operation_id="tasks_me_config_task_defaults_create",
        request=TasksTaskDefaultsUpdateSerializer,
        responses={200: TasksTaskDefaultsSerializer},
        description="Update your per-project defaults for new tasks. Fields you leave out keep their stored value.",
    )
    @action(methods=["POST"], detail=False, url_path="task_defaults", required_scopes=["task:write"])
    def task_defaults(self, request: Request, *args, **kwargs) -> Response:
        serializer = TasksTaskDefaultsUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        defaults = task_defaults_store.update_user_task_defaults(
            self.team_id, _user_id(request), dict(serializer.validated_data)
        )
        return Response(TasksTaskDefaultsSerializer(defaults).data)
