from collections.abc import Callable
from typing import TypeVar, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.egress.typesafe.client import TypesafeNotConfigured
from posthog.egress.typesafe.transport import TypesafeEgressBudgetExhausted
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Tag, User
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.rate_limit import (
    AIObservabilitySummarizationBurstThrottle,
    AIObservabilitySummarizationDailyThrottle,
    AIObservabilitySummarizationSustainedThrottle,
)

from products.product_analytics.backend.presentation.typesafe_metadata import (
    DashboardCandidate,
    SubjectContext,
    suggest_dashboard,
    suggest_description,
    suggest_tags,
    suggest_title,
    suggestions_enabled,
    validate_metadata_query,
)

_MAX_TILE_NAMES = 100
_MAX_DASHBOARDS = 254

T = TypeVar("T")


class TypesafeBusy(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "TypeSafe suggestions are busy right now. Try again in a minute."


class TypesafeSuggestionSubject(models.TextChoices):
    INSIGHT = "insight", "Insight"
    DASHBOARD = "dashboard", "Dashboard"


class TypesafeSubjectSerializer(serializers.Serializer):
    subject = serializers.ChoiceField(
        choices=TypesafeSuggestionSubject.choices,
        help_text="Whether the metadata belongs to an insight or a dashboard.",
    )
    query = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "For an insight, its query as a JSON object with kind `InsightVizNode`, `ActorsQuery`, `EventsQuery` "
            "or `GroupsQuery`. Candidates are built from it server-side; only a plain-language outline without "
            "filter values is sent to TypeSafe. Omit for a dashboard."
        ),
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=400,
        help_text="The current name. Sent to TypeSafe as context and offered as one of the candidates.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="The current description. Sent to TypeSafe as context and offered as one of the candidates.",
    )
    tile_names = serializers.ListField(
        child=serializers.CharField(max_length=400, allow_blank=True),
        required=False,
        default=list,
        max_length=_MAX_TILE_NAMES,
        help_text="For a dashboard, the names of the insights on it. Ignored for an insight.",
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("subject") == TypesafeSuggestionSubject.INSIGHT and not attrs.get("query"):
            raise ValidationError({"query": "An insight needs its query so candidates can be built from it."})
        return attrs


class TypesafeDashboardCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The dashboard id.")
    name = serializers.CharField(allow_blank=True, max_length=400, help_text="The dashboard name.")
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000, help_text="The dashboard description."
    )


class TypesafeDashboardRequestSerializer(TypesafeSubjectSerializer):
    dashboards = TypesafeDashboardCandidateSerializer(  # type: ignore[call-arg]
        many=True,
        max_length=_MAX_DASHBOARDS,
        help_text="The dashboards the insight could be added to. At most 254; TypeSafe caps a choice at 255 options.",
    )


class TypesafeTextSuggestionSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="The candidate TypeSafe picked.")
    confidence = serializers.FloatField(help_text="How concentrated TypeSafe's probability was on the pick, 0 to 1.")
    candidates = serializers.ListField(
        child=serializers.CharField(), help_text="Every candidate TypeSafe chose between, in the order sent."
    )


class TypesafeTagSuggestionSerializer(serializers.Serializer):
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="The team's existing tags TypeSafe judged to apply, most likely first.",
    )
    scores = serializers.DictField(
        child=serializers.FloatField(),
        help_text="TypeSafe's probability that each considered tag applies, keyed by tag name.",
    )


class TypesafeDashboardSuggestionSerializer(serializers.Serializer):
    dashboard_id = serializers.IntegerField(
        allow_null=True, help_text="The dashboard TypeSafe picked, or null when none clearly fits."
    )
    confidence = serializers.FloatField(help_text="How concentrated TypeSafe's probability was on the pick, 0 to 1.")


class TypesafeSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Metadata suggestions ranked by TypeSafe's Jev classifier. Every action builds candidates
    server-side and asks Jev to pick, so the frontend only ever receives one of its own candidates."""

    scope_object = "insight"
    scope_object_read_actions = ["title", "description", "tags", "dashboard"]
    scope_object_write_actions: list[str] = []

    def get_throttles(self) -> list[BaseThrottle]:
        return [
            AIObservabilitySummarizationBurstThrottle(),
            AIObservabilitySummarizationSustainedThrottle(),
            AIObservabilitySummarizationDailyThrottle(),
        ]

    def _check_access(self) -> None:
        # TypeSafe is not a listed PostHog subprocessor, so both the organization's AI approval and the
        # per-project flag must hold before any metadata leaves PostHog.
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization")
        if not suggestions_enabled(self.team):
            raise PermissionDenied("TypeSafe suggestions are not enabled for this project")

    def _context(self, data: dict[str, object]) -> SubjectContext:
        subject = cast(str, data["subject"])
        query_data = data.get("query")
        query = None
        if subject == TypesafeSuggestionSubject.INSIGHT and query_data:
            if not isinstance(query_data, dict):
                raise ValidationError({"query": "Must be a JSON object"})
            try:
                query = validate_metadata_query(query_data)
            except ValueError as error:
                raise ValidationError({"query": str(error)})
        return SubjectContext(
            subject="dashboard" if subject == TypesafeSuggestionSubject.DASHBOARD else "insight",
            name=cast(str, data.get("name") or ""),
            description=cast(str, data.get("description") or ""),
            query=query,
            tile_names=tuple(cast(list[str], data.get("tile_names") or [])),
            group_type_names=self._group_type_names() if query is not None else {},
        )

    def _group_type_names(self) -> dict[int, tuple[str, str]]:
        names: dict[int, tuple[str, str]] = {}
        for mapping in get_group_types_for_project(self.team.project_id):
            singular = mapping.get("name_singular") or mapping["group_type"]
            plural = mapping.get("name_plural") or f"{singular}s"
            names[int(mapping["group_type_index"])] = (str(singular), str(plural))
        return names

    def _report(self, kind: str, context: SubjectContext, confidence: float) -> None:
        report_user_action(
            cast(User, self.request.user),
            "typesafe metadata suggested",
            {"suggestion": kind, "subject": context.subject, "confidence": confidence},
            team=self.team,
        )

    @validated_request(
        request_serializer=TypesafeSubjectSerializer,
        responses={
            200: OpenApiResponse(response=TypesafeTextSuggestionSerializer, description="The title TypeSafe picked."),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest a title with TypeSafe",
        description=(
            "Builds candidate titles from the query or tile names and asks TypeSafe's Jev classifier to pick the "
            "best one. Jev only picks; it never writes text."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def title(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        suggestion = self._call(lambda: suggest_title(context))
        self._report("title", context, suggestion.confidence)
        return Response(
            {"value": suggestion.value, "confidence": suggestion.confidence, "candidates": list(suggestion.candidates)}
        )

    @validated_request(
        request_serializer=TypesafeSubjectSerializer,
        responses={
            200: OpenApiResponse(
                response=TypesafeTextSuggestionSerializer, description="The description TypeSafe picked."
            ),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest a description with TypeSafe",
        description=(
            "Builds candidate descriptions from the query or tile names and asks TypeSafe's Jev classifier to pick "
            "the best one. Jev only picks; it never writes text."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def description(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        suggestion = self._call(lambda: suggest_description(context))
        self._report("description", context, suggestion.confidence)
        return Response(
            {"value": suggestion.value, "confidence": suggestion.confidence, "candidates": list(suggestion.candidates)}
        )

    @validated_request(
        request_serializer=TypesafeSubjectSerializer,
        responses={
            200: OpenApiResponse(response=TypesafeTagSuggestionSerializer, description="The tags that apply."),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest tags with TypeSafe",
        description=(
            "Asks TypeSafe's Jev classifier, for each tag the project already uses, whether it applies to the "
            "insight or dashboard. Returns the tags above the confidence threshold. No new tags are invented."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def tags(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        available = list(Tag.objects.filter(team=self.team).values_list("name", flat=True).distinct().order_by("name"))
        suggestion = self._call(lambda: suggest_tags(context, available))
        self._report("tags", context, max(suggestion.scores.values(), default=0.0))
        return Response({"tags": list(suggestion.tags), "scores": dict(suggestion.scores)})

    @validated_request(
        request_serializer=TypesafeDashboardRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TypesafeDashboardSuggestionSerializer, description="The dashboard TypeSafe picked."
            ),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest a dashboard for an insight with TypeSafe",
        description=(
            "Asks TypeSafe's Jev classifier which of the given dashboards is the best home for the insight, "
            "or none when no dashboard clearly fits."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def dashboard(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        dashboards = [
            DashboardCandidate(id=item["id"], name=item["name"], description=item.get("description") or "")
            for item in request.validated_data["dashboards"]
        ]
        suggestion = self._call(lambda: suggest_dashboard(context, dashboards))
        self._report("dashboard", context, suggestion.confidence)
        return Response({"dashboard_id": suggestion.dashboard_id, "confidence": suggestion.confidence})

    @staticmethod
    def _call(run: Callable[[], T]) -> T:
        try:
            return run()
        except TypesafeNotConfigured as error:
            raise PermissionDenied("TypeSafe suggestions are not enabled for this project") from error
        except TypesafeEgressBudgetExhausted as error:
            raise TypesafeBusy() from error
        except Exception as error:
            capture_exception(error)
            raise APIException("Couldn't get a suggestion from TypeSafe. Try again.") from error
