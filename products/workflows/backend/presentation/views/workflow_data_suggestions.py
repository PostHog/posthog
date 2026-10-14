from typing import Any

from django.db import models

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_event_source
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.workflows.backend.facade.contracts import DataSuggestionNotFound
from products.workflows.backend.facade.data_suggestions import (
    get_data_suggestions,
    needs_new_build,
    needs_new_generation,
    start_build,
    start_data_suggestions,
)

# pinned: feature flag key - the frontend gates the same surfaces on it
FEATURE_FLAG_KEY = "workflows-data-suggestions"


class DataSuggestionStepKind(models.TextChoices):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    SLACK = "slack"
    WEBHOOK = "webhook"
    DELAY = "delay"
    WAIT_UNTIL = "wait_until"
    BRANCH = "branch"
    SPLIT = "split"
    ACTION = "action"


class DataSuggestionStage(models.TextChoices):
    SIGNUP = "signup"
    ONBOARDING = "onboarding"
    TRIAL = "trial"
    PURCHASE = "purchase"
    CHURN_RISK = "churn_risk"
    FAILURE = "failure"
    SUPPORT = "support"
    OTHER = "other"


class DataSuggestionsStatus(models.TextChoices):
    READY = "ready"
    GENERATING = "generating"
    AI_NOT_APPROVED = "ai_not_approved"
    UNAVAILABLE = "unavailable"


class DataSuggestionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Opaque id of this suggestion, valid while the suggestions stay cached.")
    name = serializers.CharField(help_text="Suggested workflow name, written by AI from the project's events.")
    description = serializers.CharField(help_text="One sentence on what the workflow does.")
    reason = serializers.CharField(help_text="One sentence on why the workflow fits this project.")
    trigger_event = serializers.CharField(help_text="The project event that starts the workflow.")
    weekly_count = serializers.IntegerField(help_text="How often the trigger event fired in the last 7 days.")
    stage = serializers.ChoiceField(
        choices=DataSuggestionStage.choices,
        help_text="The customer lifecycle stage the trigger event marks. Suggestions are ranked by stage first, "
        "so welcome and onboarding flows come before busier events.",
    )
    step_outline = serializers.ListField(
        child=serializers.ChoiceField(choices=DataSuggestionStepKind.choices),
        help_text="The main planned step kinds after the trigger, in order.",
    )


class DataSuggestionsResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DataSuggestionsStatus.choices,
        help_text="ready when suggestions were made (the list can still be empty), generating while a background "
        "run makes them (poll current until it ends), ai_not_approved when the organization has not approved AI "
        "data processing, unavailable when nothing was made or the run failed.",
    )
    suggestions = DataSuggestionSerializer(
        many=True, help_text="Up to 3 suggested workflows, ranked by lifecycle stage and then by weekly volume."
    )


class DataSuggestionGenerateRequestSerializer(serializers.Serializer):
    refresh = serializers.BooleanField(
        default=False, help_text="Make new suggestions even when the cached ones are still valid."
    )


class DataSuggestionBuildRequestSerializer(serializers.Serializer):
    suggestion_id = serializers.CharField(help_text="The id of a suggestion from the list endpoint.")
    retry = serializers.BooleanField(
        default=False,
        help_text="Start a new build when the last one failed. Leave it false when asking for a running build's status.",
    )


class DataSuggestionBuildStatus(models.TextChoices):
    READY = "ready"
    BUILDING = "building"
    FAILED = "failed"


class DataSuggestionBuildResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DataSuggestionBuildStatus.choices,
        help_text="ready when the draft is built, building while a background build runs (call build again to "
        "check), failed when the plan did not produce a valid workflow. A failed result is reported once, so the "
        "next call starts a new build.",
    )
    workflow = serializers.JSONField(
        allow_null=True,
        help_text="With status ready: a validated draft workflow (name, description, trigger, actions, edges, "
        "conversion, exit_condition) that the workflow create endpoint accepts from this caller. Nothing is saved "
        "by this call. Null otherwise.",
    )
    uses_saved_template = serializers.BooleanField(help_text="Whether an email step reuses a saved email template.")


class WorkflowDataSuggestionsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Workflow ideas written by AI from the project's own events. Both calls are free for the customer."""

    scope_object = "hog_flow"
    # These actions read the whole project and create drafts, so access to a single workflow is not enough.
    requires_resource_level_access = True
    scope_object_read_actions = ["current"]
    # Both calls can run ClickHouse and the models, so a read-only key cannot cause that spend.
    scope_object_write_actions = ["generate", "build"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # The cards carry the project's event names and weekly counts, so a key also needs the scope that reads them.
        access = "read" if self.action in self.scope_object_read_actions else "write"
        return [f"hog_flow:{access}", "query:read"]

    def get_throttles(self):
        # The AI budget is per user and shared with other AI features, so only a call that can run the LLM counts
        # against it. A generate call answered from the cache does not.
        if (self.action == "build" and self._starts_build()) or (
            self.action == "generate" and self._starts_generation()
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def _starts_build(self) -> bool:
        # Asking again while a build runs, or for a finished build, costs no model time, so only a new build counts.
        payload = DataSuggestionBuildRequestSerializer(data=self.request.data)
        return not payload.is_valid() or needs_new_build(
            team=self.team,
            suggestion_id=payload.validated_data["suggestion_id"],
            caller=get_event_source(self.request).value,
            retry=payload.validated_data["retry"],
        )

    def _starts_generation(self) -> bool:
        # Joining a run that is already going costs no model time, so it is not throttled. Invalid input is throttled.
        payload = DataSuggestionGenerateRequestSerializer(data=self.request.data)
        return not payload.is_valid() or needs_new_generation(team=self.team, refresh=payload.validated_data["refresh"])

    @extend_schema(operation_id="workflow_data_suggestions_current", responses={200: DataSuggestionsResponseSerializer})
    @action(detail=False, methods=["get"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        self._user_with_feature(request)
        return Response(DataSuggestionsResponseSerializer(get_data_suggestions(team=self.team)).data)

    @extend_schema(
        operation_id="workflow_data_suggestions_generate",
        request=DataSuggestionGenerateRequestSerializer,
        responses={200: DataSuggestionsResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def generate(self, request: Request, **kwargs: Any) -> Response:
        user = self._user_with_feature(request)
        payload = DataSuggestionGenerateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = start_data_suggestions(team=self.team, user=user, refresh=payload.validated_data["refresh"])
        return Response(DataSuggestionsResponseSerializer(result).data)

    @extend_schema(
        operation_id="workflow_data_suggestions_build",
        request=DataSuggestionBuildRequestSerializer,
        responses={200: DataSuggestionBuildResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def build(self, request: Request, **kwargs: Any) -> Response:
        user = self._user_with_feature(request)
        payload = DataSuggestionBuildRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            built = start_build(
                team=self.team,
                user=user,
                suggestion_id=payload.validated_data["suggestion_id"],
                retry=payload.validated_data["retry"],
                event_source=get_event_source(request),
            )
        except DataSuggestionNotFound:
            raise NotFound("This suggestion has expired. Refresh the page to get new ones.")
        return Response(DataSuggestionBuildResponseSerializer(built).data)

    def _user_with_feature(self, request: Request) -> User:
        user = request.user
        if (
            not isinstance(user, User)
            or not user.distinct_id
            or not posthoganalytics.feature_enabled(
                FEATURE_FLAG_KEY,
                user.distinct_id,
                groups={"organization": str(self.organization.id)},
                group_properties={"organization": {"id": str(self.organization.id)}},
            )
        ):
            raise PermissionDenied("This feature is not available.")
        return user
