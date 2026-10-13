from typing import Any

from django.db import models

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import EventSource
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.workflows.backend.facade.contracts import DataSuggestionBuildFailed, DataSuggestionNotFound
from products.workflows.backend.facade.data_suggestions import (
    build_data_suggestion,
    get_data_suggestions,
    has_cached_data_suggestions,
    start_data_suggestions,
)
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer

logger = structlog.get_logger(__name__)

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


class DataSuggestionBuildResponseSerializer(serializers.Serializer):
    workflow = serializers.JSONField(
        help_text="A validated draft workflow (name, description, trigger, actions, edges, conversion, "
        "exit_condition), ready to send to the workflow create endpoint. Nothing is saved by this call."
    )
    uses_saved_template = serializers.BooleanField(help_text="Whether an email step reuses a saved email template.")


class WorkflowDataSuggestionsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Workflow ideas written by AI from the project's own events. Both calls are free for the customer."""

    scope_object = "hog_flow"
    scope_object_read_actions = ["current"]
    # Both calls can run ClickHouse and the models, so a read-only key cannot cause that spend.
    scope_object_write_actions = ["generate", "build"]

    def get_throttles(self):
        # The AI budget is per user and shared with other AI features, so only a call that can run the LLM counts
        # against it. A generate call answered from the cache does not.
        if self.action == "build" or (
            self.action == "generate" and (self._wants_refresh() or not has_cached_data_suggestions(team=self.team))
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def _wants_refresh(self) -> bool:
        # Parsed like the endpoint parses it, so every value it accepts as true is throttled. Invalid input counts
        # as a refresh, so it is throttled too.
        payload = DataSuggestionGenerateRequestSerializer(data=self.request.data)
        return not payload.is_valid() or payload.validated_data["refresh"]

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
            built = build_data_suggestion(
                team=self.team,
                user=user,
                suggestion_id=payload.validated_data["suggestion_id"],
                is_valid_draft=self._is_valid_draft,
            )
        except DataSuggestionNotFound:
            raise NotFound("This suggestion has expired. Refresh the page to get new ones.")
        except DataSuggestionBuildFailed:
            return Response(
                {"detail": "We couldn't build this workflow. Try again, or start from a template."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(DataSuggestionBuildResponseSerializer(built).data)

    def _is_valid_draft(self, workflow: dict[str, Any]) -> bool:
        # The draft leaves credentials, channels and filters blank for the team, so it is checked the way the
        # editor saves a draft. The graph wiring is checked in full, and enabling it later validates every step.
        serializer = HogFlowSerializer(
            data={**workflow, "status": "draft"},
            context={
                "team_id": self.team.id,
                "get_team": lambda: self.team,
                "is_draft": True,
                "event_source": EventSource.WEB,
            },
        )
        try:
            validate_graph(workflow["actions"], workflow["edges"])
            serializer.is_valid(raise_exception=True)
        except ValidationError as error:
            logger.info(
                "workflows.data_suggestions.invalid_workflow", team_id=self.team.id, errors=str(error.detail)[:500]
            )
            return False
        return True

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
