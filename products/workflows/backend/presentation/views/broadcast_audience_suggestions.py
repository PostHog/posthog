from typing import Any

from django.db import models

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.workflows.backend.facade.audience_suggestions import (
    can_read_email,
    get_audience_suggestions,
    is_enabled,
    needs_new_generation,
    start_audience_suggestions,
)
from products.workflows.backend.presentation.views.workflow_data_suggestions import (
    DataSuggestionGenerateRequestSerializer,
    DataSuggestionsStatus,
)


class AudienceSuggestionKind(models.TextChoices):
    NOT_YET = "not_yet"
    REGULARS = "regulars"
    LAPSED = "lapsed"


class AudienceSuggestionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Opaque id of this suggestion, valid while the suggestions stay cached.")
    name = serializers.CharField(help_text="Suggested audience name, written by AI from the project's events.")
    description = serializers.CharField(
        help_text="Who the people are and what to tell them. Used as the cohort description and the email brief."
    )
    reason = serializers.CharField(help_text="One sentence on why the audience is worth a broadcast.")
    kind = serializers.ChoiceField(
        choices=AudienceSuggestionKind.choices,
        help_text="not_yet: did event in the window but not missing_event. regulars: did event at least min_count "
        "times in the window. lapsed: did event in the last 90 days but not in the window.",
    )
    event = serializers.CharField(help_text="The project event the audience is built on.")
    missing_event = serializers.CharField(
        allow_null=True, help_text="For not_yet: the event the audience has not done yet. Null otherwise."
    )
    window_days = serializers.IntegerField(help_text="The time window in days.")
    min_count = serializers.IntegerField(
        allow_null=True, help_text="For regulars: how many times the event must happen in the window."
    )
    reachable_count = serializers.IntegerField(
        help_text="People in the audience with an email address, counted when the suggestion was made."
    )
    cohort_filters = serializers.JSONField(
        help_text="The audience's cohort filters, in the cohorts endpoint's `filters` format. Saved as a static cohort."
    )


class AudienceSuggestionsResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DataSuggestionsStatus.choices,
        help_text="ready when suggestions were made (the list can still be empty), generating while a background "
        "run makes them (poll current until it ends), ai_not_approved when the organization has not approved AI "
        "data processing, unavailable when nothing was made or the run failed.",
    )
    suggestions = AudienceSuggestionSerializer(many=True, help_text="Up to 3 suggested broadcast audiences.")


class BroadcastAudienceSuggestionsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Broadcast audiences written by AI from the project's own events. Both calls are free for the customer."""

    scope_object = "hog_flow"
    requires_resource_level_access = True
    scope_object_read_actions = ["current"]
    scope_object_write_actions = ["generate"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # The cards carry the project's event names and audience sizes, so a key also needs the scope that reads them.
        access = "read" if self.action in self.scope_object_read_actions else "write"
        return [f"hog_flow:{access}", "query:read"]

    def get_throttles(self):
        if self.action == "generate" and self._starts_generation():
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def _starts_generation(self) -> bool:
        payload = DataSuggestionGenerateRequestSerializer(data=self.request.data)
        return not payload.is_valid() or needs_new_generation(team=self.team, refresh=payload.validated_data["refresh"])

    @extend_schema(
        operation_id="broadcast_audience_suggestions_current", responses={200: AudienceSuggestionsResponseSerializer}
    )
    @action(detail=False, methods=["get"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        self._user_with_feature(request)
        return Response(AudienceSuggestionsResponseSerializer(get_audience_suggestions(team=self.team)).data)

    @extend_schema(
        operation_id="broadcast_audience_suggestions_generate",
        request=DataSuggestionGenerateRequestSerializer,
        responses={200: AudienceSuggestionsResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def generate(self, request: Request, **kwargs: Any) -> Response:
        user = self._user_with_feature(request)
        payload = DataSuggestionGenerateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = start_audience_suggestions(team=self.team, user=user, refresh=payload.validated_data["refresh"])
        return Response(AudienceSuggestionsResponseSerializer(result).data)

    def _user_with_feature(self, request: Request) -> User:
        user = request.user
        if not isinstance(user, User) or not is_enabled(user, str(self.organization.id)):
            raise PermissionDenied("This feature is not available.")
        # The cards are shared by the whole project and count people by email, so they stay hidden from anyone
        # whose access hides email addresses.
        if not can_read_email(user, self.team.id):
            raise PermissionDenied("Audience ideas need access to people's email addresses.")
        return user
