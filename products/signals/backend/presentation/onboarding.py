from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.exceptions import InsufficientScope
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_oauth_request
from posthog.permissions import APIScopePermission, get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade.onboarding import (
    InboxOnboarding,
    InboxOnboardingPermissionError,
    InboxOnboardingValidationError,
    QuickActivationBlocker,
    can_create_onboarding_scout,
    onboarding_first_report_statuses,
    onboarding_priorities,
    onboarding_setup_modes,
    onboarding_source_products,
    onboarding_source_types,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission
from products.signals.backend.presentation.scout_suggestion_serializers import ScoutSuggestionItemSerializer


def credential_may_start_tasks(request: Request) -> bool:
    """Whether the request's credential may start a task run, as `task:write` allows.

    For a write whose scope depends on the request body. Session auth has no scopes, so team
    membership and access control gate it instead.
    """
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, ["task:write"])


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


class InboxOnboardingOrigin(models.TextChoices):
    APP = "app", "App"
    AGENT = "agent", "Agent"


class InboxOnboardingExposureSerializer(serializers.Serializer):
    onboarding_origin = serializers.ChoiceField(
        choices=InboxOnboardingOrigin.choices,
        required=False,
        help_text="Where setup started: the app or a link from an agent.",
    )


class InboxOnboardingDraftSerializer(serializers.Serializer):
    onboarding_origin = serializers.ChoiceField(
        choices=InboxOnboardingOrigin.choices,
        required=False,
        help_text="Where setup started: the app or a link from an agent.",
    )
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
    error_tracking_backfill = serializers.ChoiceField(
        choices=InboxOnboardingJobStatus.choices,
        required=False,
        help_text="Dispatch status of the backfill of existing errors, when quick activation from an agent added Error tracking.",
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
    github_connected = serializers.BooleanField(
        required=False,
        help_text="Whether this project has a GitHub connection. It does not check which repositories the connection can read.",
    )
    github_optional_available = serializers.BooleanField(
        required=False, help_text="Whether this project can activate Self-driving without connecting GitHub."
    )
    setup_default_skills = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Canonical scout skill names that quick setup enables for this project, with the general scout first.",
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


class QuickActivationState(models.TextChoices):
    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"


class QuickActivationPricingKind(models.TextChoices):
    FREE_TRIAL = "free_trial", "Free trial"
    TRIAL_CLAIMED = "trial_claimed", "Trial already claimed by this project"
    PAID_PLAN = "paid_plan", "Paid plan"
    EXISTING_PLAN = "existing_plan", "Existing plan"


class QuickActivationBlockerSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable reason that quick activation is unavailable.")
    message = serializers.CharField(help_text="What prevents quick activation, in words to show the person.")


class QuickActivationGitHubSerializer(serializers.Serializer):
    connected = serializers.BooleanField(help_text="Whether the project has a GitHub connection.")
    repositories = serializers.ListField(
        child=serializers.CharField(),
        help_text="Repositories, as owner/name, that agents can read through the GitHub connection.",
    )
    more_repositories = serializers.BooleanField(
        help_text="True when the connection can read more repositories than listed, or the list could not be read."
    )


class QuickActivationPricingSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=QuickActivationPricingKind.choices, help_text="Which pricing terms activation starts."
    )
    summary = serializers.CharField(help_text="The cost terms in plain words, to show the person before activation.")
    report_limit = serializers.IntegerField(allow_null=True, help_text="Reports included in the free trial, if any.")
    allowance_microusd = serializers.IntegerField(
        allow_null=True, help_text="Usage included in the free trial, in millionths of a US dollar, if any."
    )


class QuickActivationSourceSerializer(serializers.Serializer):
    source_product = serializers.ChoiceField(
        choices=onboarding_source_products(), help_text="Source product that activation turns on."
    )
    source_type = serializers.ChoiceField(
        choices=onboarding_source_types(), help_text="Signal type that activation turns on."
    )
    enabled_now = serializers.BooleanField(
        allow_null=True, help_text="Whether the source is on now. Null means the project has no setting for it yet."
    )


class QuickActivationScoutSerializer(serializers.Serializer):
    skill_name = serializers.CharField(help_text="Scout that activation turns on.")
    title = serializers.CharField(help_text="Scout name to show the person.")
    run_interval_minutes = serializers.IntegerField(help_text="How often the scout runs, in minutes.")
    run_cron_schedule = serializers.CharField(
        allow_null=True, help_text="Cron schedule in the project timezone. It replaces the interval when set."
    )
    enabled_now = serializers.BooleanField(help_text="Whether the scout is on now.")


@extend_schema_serializer(many=False)
class QuickActivationPlanSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=QuickActivationState.choices, help_text="Whether Self-driving setup has started in this project."
    )
    can_activate = serializers.BooleanField(
        help_text="Whether quick activation can run now. When false, `blockers` says why."
    )
    fingerprint = serializers.CharField(
        help_text="Identifies this plan. Activation takes it and refuses when the plan changed since."
    )
    blockers = QuickActivationBlockerSerializer(many=True, help_text="Reasons quick activation can't run now.")
    github = QuickActivationGitHubSerializer(help_text="The GitHub access agents get.")
    pricing = QuickActivationPricingSerializer(help_text="The cost terms that activation starts.")
    github_optional = serializers.BooleanField(
        help_text="Whether this project activates the GitHub-optional pilot, which keeps automatic pull requests off."
    )
    automatic_implementation = serializers.BooleanField(
        help_text="Whether activation turns on automatic pull requests for reports at `implementation_priority` or higher."
    )
    implementation_priority = serializers.ChoiceField(
        choices=onboarding_priorities(), help_text="Lowest report priority that automatic pull requests apply to."
    )
    sources = QuickActivationSourceSerializer(many=True, help_text="Signal sources that activation turns on.")
    scanner_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Enabled Replay Vision scanners whose findings activation turns on."
    )
    scouts = QuickActivationScoutSerializer(many=True, help_text="Scouts that activation turns on.")


class QuickActivationRequestSerializer(serializers.Serializer):
    plan_fingerprint = serializers.CharField(
        max_length=64,
        help_text="`fingerprint` from the quick activation plan the person approved.",
    )


class InboxOnboardingPermission(BasePermission):
    message = "Task agents cannot change onboarding settings."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in SAFE_METHODS or not is_sandbox_oauth_request(request)


class InboxOnboardingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, InboxOnboardingPermission]
    scope_object = "inbox"
    requires_resource_level_access = True
    serializer_class = InboxOnboardingStateSerializer
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: object) -> list[str]:
        return ["inbox:read"] if request.method in ("GET", "HEAD", "OPTIONS") else ["inbox:write"]

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
                raise InsufficientScope(
                    sorted(required - allowed),
                    detail="Your API key does not have permission to access these scout choices.",
                )
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

    @extend_schema(
        responses=QuickActivationPlanSerializer,
        summary="Get the quick activation plan",
        description=(
            "What quick activation would turn on in this project: signal sources, Replay Vision scanners, scouts, "
            "automatic pull requests, the GitHub access agents get and the cost terms, plus anything that blocks it. "
            "Changes nothing."
        ),
    )
    @action(detail=False, methods=["GET"], url_path="quick_activation")
    def quick_activation(self, request: Request, *args: object, **kwargs: object) -> Response:
        plan = self._service().quick_activation_plan(get_authenticator_scopes(request.successful_authenticator))
        if is_sandbox_oauth_request(request):
            plan = replace(
                plan,
                blockers=(
                    *plan.blockers,
                    QuickActivationBlocker(code="missing_permission", message=InboxOnboardingPermission.message),
                ),
            )
        return Response(QuickActivationPlanSerializer(plan).data)

    @extend_schema(
        request=QuickActivationRequestSerializer,
        responses={
            200: InboxOnboardingStateSerializer,
            409: OpenApiResponse(
                description=(
                    "Not activated. The plan changed since it was shown, setup already started, GitHub isn't "
                    "connected, or the plan has a blocker. `code` says which."
                )
            ),
        },
        summary="Activate quick setup",
        description=(
            "Turn on Self-driving with the quick activation plan the person approved, identified by its "
            "fingerprint. Refuses without changing anything when the plan changed since it was shown."
        ),
    )
    @quick_activation.mapping.post
    def activate_quick_activation(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = QuickActivationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(
                self._service().activate_quick_setup(
                    get_authenticator_scopes(request.successful_authenticator),
                    serializer.validated_data["plan_fingerprint"],
                )
            )
        except (InboxOnboardingPermissionError, PermissionError) as error:
            raise PermissionDenied(str(error)) from error
        except (InboxOnboardingValidationError, ValueError) as error:
            raise serializers.ValidationError(str(error)) from error

    @extend_schema(request=InboxOnboardingExposureSerializer, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def expose(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingExposureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(self._service().expose(serializer.validated_data.get("onboarding_origin", "app")))

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
        if serializer.validated_data["automatic_implementation"] and not credential_may_start_tasks(request):
            raise InsufficientScope(
                ["task:write"], detail="Turning on automatic implementation requires the task:write scope."
            )
        try:
            return Response(self._service().complete(dict(serializer.data)))
        except InboxOnboardingPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except InboxOnboardingValidationError as error:
            raise serializers.ValidationError(str(error)) from error
