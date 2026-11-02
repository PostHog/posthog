from __future__ import annotations

from typing import Any, cast

from django.db import models

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_oauth_request
from posthog.permissions import APIScopePermission, get_authenticator_scopes

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade.onboarding import (
    InboxOnboarding,
    InboxOnboardingPermissionError,
    InboxOnboardingValidationError,
    can_create_onboarding_scout,
    onboarding_first_report_statuses,
    onboarding_priorities,
    onboarding_setup_modes,
    onboarding_source_products,
    onboarding_source_types,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission
from products.signals.backend.presentation.scout_suggestion_serializers import ScoutSuggestionItemSerializer


class InboxOnboardingStep(models.TextChoices):
    SIGNALS = "signals", "Signals"
    SCOUTS = "scouts", "Scouts"
    GITHUB = "github", "GitHub"


class InboxOnboardingSourceSerializer(serializers.Serializer):
    source_product = serializers.ChoiceField(
        choices=onboarding_source_products(), help_text="Source product selected during setup."
    )
    source_type = serializers.ChoiceField(
        choices=onboarding_source_types(), help_text="Signal type selected during setup."
    )
    enabled = serializers.BooleanField(help_text="Whether this source should be enabled at activation.")


class InboxActivationMode(models.TextChoices):
    GITHUB_OPTIONAL = "github_optional", "GitHub optional"


class InboxOnboardingDraftSerializer(serializers.Serializer):
    activation_mode = serializers.ChoiceField(
        choices=InboxActivationMode.choices,
        required=False,
        help_text="Activate the GitHub-optional pilot. Requires project eligibility and leaves automatic implementation off.",
    )
    step = serializers.ChoiceField(choices=InboxOnboardingStep.choices, help_text="Step to resume after returning.")
    setup_mode = serializers.ChoiceField(
        choices=onboarding_setup_modes(),
        required=False,
        help_text="How setup was chosen: quick activation from the welcome screen, or the guided steps.",
    )
    sources: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=InboxOnboardingSourceSerializer(), max_length=50, help_text="Staged signal source choices."
    )
    scanner_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=100, help_text="Existing enabled scanners selected to emit signals."
    )
    suggestions: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ScoutSuggestionItemSerializer(), max_length=5, help_text="Selected scout suggestion drafts."
    )
    activation_scouts = serializers.ListField(
        child=serializers.CharField(max_length=200),
        max_length=50,
        required=False,
        help_text="Scouts enabled by an unfinished activation, retained to undo later deselections.",
    )
    automatic_implementation = serializers.BooleanField(help_text="Opt in to automatically creating pull requests.")
    implementation_priority = serializers.ChoiceField(
        choices=onboarding_priorities(),
        help_text="Lowest priority to implement automatically; P1 includes P0 and P1.",
    )

    def validate_suggestions(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if any(len(item["draft_body"]) > 100_000 for item in suggestions):
            raise serializers.ValidationError("A scout draft is too long.")
        return suggestions


class InboxOnboardingJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    STARTED = "started", "Started"
    SKIPPED = "skipped", "Unavailable"
    FAILED = "failed", "Failed"


class InboxOnboardingJobsSerializer(serializers.Serializer):
    scout = serializers.ChoiceField(
        choices=InboxOnboardingJobStatus.choices, help_text="Dispatch status of the first-report scout run."
    )
    recommendations = serializers.ChoiceField(
        choices=InboxOnboardingJobStatus.choices, help_text="Dispatch status of personalized scout recommendations."
    )


@extend_schema_serializer(many=False)
class FirstReportStateSerializer(serializers.Serializer):
    scout_run_id = serializers.UUIDField(
        required=False, help_text="Scout run ID for inspecting the investigation through the scout API."
    )
    task_id = serializers.UUIDField(
        required=False, help_text="Task ID for following the investigation's live activity."
    )
    task_run_id = serializers.UUIDField(
        required=False, help_text="Task run ID for following the investigation's live activity."
    )
    started_at = serializers.DateTimeField(required=False, help_text="When the investigation's task run started.")
    status = serializers.ChoiceField(
        choices=onboarding_first_report_statuses(), help_text="Progress of the first investigation."
    )
    report_id = serializers.UUIDField(
        required=False, help_text="The first useful report produced by the investigation."
    )
    checked_products = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Products checked during the investigation."
    )
    missing_data = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Data or history needed for a reliable finding."
    )


@extend_schema_serializer(many=False)
class InboxOnboardingStateSerializer(serializers.Serializer):
    github_optional_available = serializers.BooleanField(
        required=False, help_text="Whether this project can activate Self-driving without connecting GitHub."
    )
    first_report_completion_notification = serializers.BooleanField(
        required=False,
        help_text="Whether the current user can receive an in-app notification when this investigation finishes.",
    )
    first_report_notification_email = serializers.EmailField(
        required=False,
        allow_null=True,
        help_text="The current user's email when enrolled for a first-report notification.",
    )
    first_report = FirstReportStateSerializer(required=False, allow_null=True, help_text="First investigation outcome.")
    jobs = InboxOnboardingJobsSerializer(required=False, help_text="Background work started by quick activation.")
    draft = InboxOnboardingDraftSerializer(allow_null=True, help_text="Saved setup choices, without activating them.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When verified setup completed.")


class InboxOnboardingPermission(BasePermission):
    message = "Task agents cannot change onboarding settings."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in SAFE_METHODS or not is_sandbox_oauth_request(request)


class InboxOnboardingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, InboxOnboardingPermission]
    scope_object = "task"
    requires_resource_level_access = True
    serializer_class = InboxOnboardingStateSerializer
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: object) -> list[str]:
        return ["task:read"] if request.method in ("GET", "HEAD", "OPTIONS") else ["task:write"]

    def _check_scout_access(self, request: Request) -> None:
        permission = ScoutCanonicalTeamAccessPermission()
        if not permission.has_permission(request, self):
            raise PermissionDenied(permission.message)

    def _check_suggestion_access(self, request: Request, *, write: bool = False) -> None:
        self._check_scout_access(request)
        scopes = get_authenticator_scopes(request.successful_authenticator)
        required = {"signal_scout:write", "llm_skill:write"} if write else {"signal_scout:read"}
        if scopes is not None and "*" not in scopes:
            allowed = set(scopes)
            if "signal_scout:write" in allowed:
                allowed.add("signal_scout:read")
            if not required.issubset(allowed):
                raise PermissionDenied("Your API key does not have permission to access these scout choices.")
        canonical_team = self.team.parent_team or self.team
        user = cast(User, request.user)
        access = UserAccessControl(user=user, team=canonical_team)
        if not access.check_access_level_for_resource("signal_scout", "editor" if write else "viewer"):
            raise PermissionDenied("You do not have access to these scout choices.")
        if write and not can_create_onboarding_scout(user, canonical_team):
            raise PermissionDenied("Saving scout choices requires editor access to skills.")

    def _service(self) -> InboxOnboarding:
        return InboxOnboarding(
            self.team,
            cast(User, self.request.user),
            lambda write: self._check_suggestion_access(self.request, write=write),
        )

    @extend_schema(request=None, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def expose(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(self._service().expose())

    @extend_schema(responses=InboxOnboardingStateSerializer)
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(self._service().state())

    @extend_schema(request=InboxOnboardingDraftSerializer, responses=InboxOnboardingStateSerializer)
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(self._service().save_draft(dict(serializer.data)))
        except InboxOnboardingValidationError as error:
            raise serializers.ValidationError(str(error)) from error

    @extend_schema(request=InboxOnboardingDraftSerializer, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def complete(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if any(source["source_product"] == "signals_scout" for source in serializer.validated_data["sources"]):
            self._check_scout_access(request)
        try:
            return Response(self._service().complete(dict(serializer.data)))
        except InboxOnboardingPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except InboxOnboardingValidationError as error:
            raise serializers.ValidationError(str(error)) from error
