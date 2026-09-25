from collections.abc import Callable
from typing import TypeVar, cast

from django.db.models import Count

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models import Tag, User
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from products.ml_inference.backend.facade.contracts import (
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionsDisabledError,
)
from products.product_analytics.backend.presentation.metadata_suggestions import (
    MAX_TAGS,
    ActorWords,
    InsightContext,
    suggest_tags,
    suggest_title,
    suggestions_enabled,
    validate_metadata_query,
)

T = TypeVar("T")

# The gateway answers these when the decision hosts are saturated or restarting, so a retry can succeed.
_BUSY_STATUSES = {status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_502_BAD_GATEWAY, status.HTTP_503_SERVICE_UNAVAILABLE}


class MetadataSuggestionsBusy(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Suggestions are busy right now. Try again in a minute."


class MetadataSuggestionBurstThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "product_analytics_metadata_suggestion_burst"
    rate = "30/minute"


class MetadataSuggestionSustainedThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "product_analytics_metadata_suggestion_sustained"
    rate = "300/hour"


class InsightMetadataSuggestionRequestSerializer(serializers.Serializer):
    query = serializers.JSONField(
        help_text=(
            "The insight's query as a JSON object with kind `InsightVizNode`, `ActorsQuery`, `EventsQuery` or "
            "`GroupsQuery`. Candidates are built from it server-side. The model sees only a plain-language outline, "
            "and filter values that look like personal data are left out."
        ),
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=400,
        help_text="The current name. Given to the model as context and offered as one of the candidates.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="The current description. Given to the model as context only.",
    )


class InsightTitleSuggestionSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="The candidate title the model picked.")
    confidence = serializers.FloatField(help_text="How concentrated the model's probability was on the pick, 0 to 1.")
    candidates = serializers.ListField(
        child=serializers.CharField(), help_text="Every candidate the model chose between, in the order sent."
    )
    runner_up = serializers.CharField(
        allow_null=True, help_text="The second most likely candidate, or null when there was only one."
    )


class InsightTagSuggestionSerializer(serializers.Serializer):
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="The project's existing tags the model judged to apply, most likely first.",
    )
    scores = serializers.DictField(
        child=serializers.FloatField(),
        help_text="The model's probability that each considered tag applies, keyed by tag name.",
    )


class MetadataSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Title and tag suggestions for an insight, ranked by the Jev decision model. Every action builds
    candidates server-side and asks Jev to pick, so the frontend only ever receives one of its own candidates."""

    scope_object = "insight"
    scope_object_read_actions = ["title", "tags"]
    scope_object_write_actions: list[str] = []

    def get_throttles(self) -> list[BaseThrottle]:
        return [MetadataSuggestionBurstThrottle(), MetadataSuggestionSustainedThrottle()]

    @validated_request(
        request_serializer=InsightMetadataSuggestionRequestSerializer,
        responses={
            200: OpenApiResponse(response=InsightTitleSuggestionSerializer, description="The title the model picked."),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest an insight title",
        description=(
            "Builds candidate titles from the query and asks the Jev decision model to pick the best one. "
            "Jev only picks; it never writes text."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def title(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        suggestion = self._call(lambda: suggest_title(self.team.id, context))
        self._report("title", suggestion.confidence, candidate_count=len(suggestion.candidates))
        return Response(InsightTitleSuggestionSerializer(instance=suggestion).data)

    @validated_request(
        request_serializer=InsightMetadataSuggestionRequestSerializer,
        responses={
            200: OpenApiResponse(response=InsightTagSuggestionSerializer, description="The tags that apply."),
            403: OpenApiResponse(description="AI processing is not approved, or the project is not in the rollout."),
        },
        summary="Suggest insight tags",
        description=(
            "Asks the Jev decision model, for each of the project's most used tags, whether it applies to the "
            "insight. Returns the tags above the confidence threshold. No new tags are invented."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def tags(self, request: ValidatedRequest, **kwargs) -> Response:
        self._check_access()
        context = self._context(request.validated_data)
        available = list(
            Tag.objects.filter(team_id=self.team.id)
            .values("name")
            .annotate(uses=Count("tagged_items"))
            .order_by("-uses", "name")
            .values_list("name", flat=True)[:MAX_TAGS]
        )
        suggestion = self._call(lambda: suggest_tags(self.team.id, context, available))
        self._report(
            "tags",
            max(suggestion.scores.values(), default=0.0),
            candidate_count=len(suggestion.scores),
            suggested_count=len(suggestion.tags),
        )
        return Response(InsightTagSuggestionSerializer(instance=suggestion).data)

    def _check_access(self) -> None:
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization")
        if not suggestions_enabled(self.team):
            raise PermissionDenied("Suggestions are not enabled for this project")

    def _context(self, data: dict[str, object]) -> InsightContext:
        query_data = data.get("query")
        if not isinstance(query_data, dict):
            raise ValidationError({"query": "Must be a JSON object"})
        try:
            query = validate_metadata_query(query_data)
        except ValueError as error:
            raise ValidationError({"query": str(error)})
        return InsightContext(
            query=query,
            name=cast(str, data.get("name") or ""),
            description=cast(str, data.get("description") or ""),
            group_type_names=self._group_type_names(),
        )

    def _group_type_names(self) -> dict[int, ActorWords]:
        names: dict[int, ActorWords] = {}
        for mapping in get_group_types_for_project(self.team.project_id):
            singular = mapping.get("name_singular") or mapping["group_type"]
            plural = mapping.get("name_plural") or f"{singular}s"
            names[int(mapping["group_type_index"])] = ActorWords(singular=str(singular), plural=str(plural))
        return names

    def _report(self, kind: str, confidence: float, **counts: int) -> None:
        report_user_action(
            cast(User, self.request.user),
            "insight metadata suggested",
            {"suggestion": kind, "confidence": confidence, **counts},
            team=self.team,
        )

    @staticmethod
    def _call(run: Callable[[], T]) -> T:
        try:
            return run()
        except (DecisionsDisabledError, GatewayNotConfiguredError) as error:
            raise PermissionDenied("Suggestions are not enabled for this project") from error
        except DecisionGatewayUnreachableError as error:
            raise MetadataSuggestionsBusy() from error
        except DecisionGatewayError as error:
            if error.status_code in _BUSY_STATUSES:
                raise MetadataSuggestionsBusy() from error
            capture_exception(error)
            raise APIException("Couldn't get a suggestion. Try again.") from error
        except Exception as error:
            capture_exception(error)
            raise APIException("Couldn't get a suggestion. Try again.") from error
