from typing import Any

from django.db import models

import posthoganalytics
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.workflows.backend.facade.contracts import DataSuggestionBuildFailed, DataSuggestionNotFound
from products.workflows.backend.facade.data_suggestions import build_data_suggestion, get_data_suggestions

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
        help_text="ready when suggestions were made (the list can still be empty), ai_not_approved when the "
        "organization has not approved AI data processing, unavailable when the AI call failed.",
    )
    suggestions = DataSuggestionSerializer(
        many=True, help_text="Up to 3 suggested workflows, ranked by lifecycle stage and then by weekly volume."
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
    scope_object_write_actions = ["build"]

    def get_throttles(self):
        # Both verbs can make an LLM call, and the default throttles exempt session requests.
        return [AIBurstRateThrottle(), AISustainedRateThrottle()]

    @extend_schema(
        operation_id="workflow_data_suggestions_current",
        parameters=[
            OpenApiParameter("refresh", bool, required=False, description="Ignore the weekly cache and ask again.")
        ],
        responses={200: DataSuggestionsResponseSerializer},
    )
    @action(detail=False, methods=["get"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        user = self._user_with_feature(request)
        result = get_data_suggestions(
            team=self.team, user=user, refresh=request.query_params.get("refresh") in ("true", "1")
        )
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
                team=self.team, user=user, suggestion_id=payload.validated_data["suggestion_id"]
            )
        except DataSuggestionNotFound:
            raise NotFound("This suggestion has expired. Refresh the page to get new ones.")
        except DataSuggestionBuildFailed:
            return Response(
                {"detail": "We couldn't build this workflow. Try again, or start from a template."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
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
