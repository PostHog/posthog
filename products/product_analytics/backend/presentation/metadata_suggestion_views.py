from typing import cast

from django.db.models import Count

import httpx
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import Tag
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from products.product_analytics.backend.presentation.metadata_suggestions import (
    MAX_TAGS,
    InsightContext,
    InsightTooLargeForSuggestions,
    TagSuggestion,
    build_insight_context,
    suggest_tags,
    suggestions_enabled,
)

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
            "The insight's query as a JSON object with kind `InsightVizNode`. The model sees only a "
            "plain-language outline of it, never the raw query."
        ),
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=400,
        help_text="The current name. Given to the model as context.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="The current description. Given to the model as context.",
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
    """Tag suggestions for an insight from the Jev decision model. Jev only judges the project's
    existing tags, so a suggestion never invents a tag."""

    scope_object = "insight"
    scope_object_read_actions = ["tags"]
    scope_object_write_actions: list[str] = []

    def get_throttles(self) -> list[BaseThrottle]:
        return [MetadataSuggestionBurstThrottle(), MetadataSuggestionSustainedThrottle()]

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
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization")
        if not suggestions_enabled(self.team):
            raise PermissionDenied("Suggestions are not enabled for this project")
        data = request.validated_data
        try:
            context = build_insight_context(
                self.team, data.get("query"), name=cast(str, data["name"]), description=cast(str, data["description"])
            )
        except ValueError as error:
            raise ValidationError({"query": str(error)})
        available = list(
            Tag.objects.filter(team_id=self.team.id)
            .values("name")
            .annotate(uses=Count("tagged_items"))
            .order_by("-uses", "name")
            .values_list("name", flat=True)[:MAX_TAGS]
        )
        return Response(InsightTagSuggestionSerializer(instance=self._suggest(context, available)).data)

    def _suggest(self, context: InsightContext, available: list[str]) -> TagSuggestion:
        try:
            return suggest_tags(self.team.id, context, available)
        except SystemOneNotConfigured as error:
            raise PermissionDenied("Suggestions are not enabled for this project") from error
        except InsightTooLargeForSuggestions as error:
            raise ValidationError("This insight is too large for suggestions. Shorten its description.") from error
        except SystemOneRequestFailed as error:
            # An unreached gateway carries no status, but a retry can succeed the same as a saturated one.
            if error.status_code in _BUSY_STATUSES or isinstance(error.__cause__, httpx.HTTPError):
                raise MetadataSuggestionsBusy() from error
            capture_exception(error)
            raise APIException("Couldn't get a suggestion. Try again.") from error
        except Exception as error:
            capture_exception(error)
            raise APIException("Couldn't get a suggestion. Try again.") from error
