from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationIdentitySourceType,
    MarketingAnalyticsRecommendationResolutionState,
    MarketingAnalyticsRecommendationRule,
)

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.marketing_analytics.backend.facade.api import (
    InvalidRecommendationIdentity,
    list_recommendation_resolutions,
    resolve_recommendation,
    restore_recommendation,
)

DEFAULT_PAGE_SIZE = 100
MAX_SUBJECT_LENGTH = 10_000
MAX_NAME_LENGTH = 400


def _choices(enum: type[StrEnum]) -> list[tuple[str, str]]:
    # Same labels as the model's TextChoices, so the OpenAPI enums keep the names derived from those classes.
    return [(member.value, member.name.replace("_", " ").title()) for member in enum]


class RecommendationIdentitySerializer(serializers.Serializer):
    rule = serializers.ChoiceField(
        choices=_choices(MarketingAnalyticsRecommendationRule), help_text="The rule that produced the recommendation."
    )
    source_type = serializers.ChoiceField(
        choices=_choices(MarketingAnalyticsRecommendationIdentitySourceType),
        help_text="The ad platform the ids belong to.",
    )
    customer_id = serializers.CharField(
        max_length=64,
        allow_blank=True,
        help_text="The Google Ads account id. Empty when the recommendation is not tied to one account.",
    )
    campaign_id = serializers.CharField(
        max_length=64,
        allow_blank=True,
        help_text="The Google Ads campaign id. Empty when the recommendation is not about one campaign.",
    )
    # The query matches resolutions on the exact identity it emitted, so a trimmed copy would never match.
    subject = serializers.CharField(
        max_length=MAX_SUBJECT_LENGTH,
        allow_blank=True,
        trim_whitespace=False,
        help_text="The search term, or the budget id for a budget recommendation. Empty when the campaign id names the subject.",
    )


class RecommendationResolutionRequestSerializer(serializers.Serializer):
    identity = RecommendationIdentitySerializer(
        help_text="The recommendation's `identity` from the recommendations query, sent as is."
    )
    name = serializers.CharField(
        max_length=MAX_NAME_LENGTH,
        required=False,
        allow_blank=True,
        default="",
        help_text="A display label for the recommendation, such as the campaign name or the search term. The activity log shows it. It is not part of the identity.",
    )
    resolution = serializers.ChoiceField(
        choices=_choices(MarketingAnalyticsRecommendationResolutionState),
        help_text="Dismissed hides the recommendation. Applied marks that someone made the change it suggests.",
    )


class RecommendationResolverSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The user's id.")
    uuid = serializers.CharField(help_text="The user's UUID.")
    distinct_id = serializers.CharField(allow_null=True, help_text="The user's distinct id.")
    first_name = serializers.CharField(help_text="The user's first name.")
    last_name = serializers.CharField(help_text="The user's last name.")
    email = serializers.EmailField(help_text="The user's email address.")


class RecommendationResolutionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The resolution id. Delete it to show the recommendation again.")
    identity = RecommendationIdentitySerializer(help_text="The identity of the resolved recommendation.")
    key = serializers.CharField(
        help_text="Opaque id of `identity`, the same as the `key` of the recommendation in the recommendations query."
    )
    name = serializers.CharField(
        allow_blank=True,
        help_text="The display label sent with the last resolution, such as the campaign name. Empty when none was sent.",
    )
    resolution = serializers.ChoiceField(
        choices=_choices(MarketingAnalyticsRecommendationResolutionState),
        help_text="Dismissed hides the recommendation. Applied marks that someone made the change it suggests.",
    )
    resolved_by = RecommendationResolverSerializer(
        allow_null=True, help_text="The user who last resolved the recommendation. Null when that user was deleted."
    )
    resolved_at = serializers.DateTimeField(help_text="When the recommendation was last resolved.")
    created_at = serializers.DateTimeField(help_text="When the recommendation was first resolved.")


class RecommendationResolutionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Marketing analytics recommendations that someone in the project dismissed or marked as applied. The
    recommendations query leaves a resolved recommendation out for everyone in the project until someone deletes
    its resolution.
    """

    scope_object = "marketing_analytics"
    permission_classes = [IsAuthenticated]
    pagination_class = PrecountedLimitOffsetPagination

    @validated_request(
        summary="List resolved recommendations",
        description="Lists the project's dismissed and applied recommendations, most recently resolved first.",
        responses={200: RecommendationResolutionSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        page = list_recommendation_resolutions(
            self.team_id,
            limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE,
            offset=paginator.get_offset(request),
        )
        paginator.set_count(page.count)
        results = self.paginate_queryset(list(page.results))
        return self.get_paginated_response(RecommendationResolutionSerializer(results, many=True).data)

    @validated_request(
        request_serializer=RecommendationResolutionRequestSerializer,
        summary="Resolve a recommendation",
        description="Dismisses a recommendation or marks it as applied. Resolving it again replaces the earlier resolution. Returns 400 when the identity's rule never produces that combination of ids.",
        responses={
            200: OpenApiResponse(response=RecommendationResolutionSerializer, description="Replaced a resolution."),
            201: OpenApiResponse(response=RecommendationResolutionSerializer, description="Created a resolution."),
        },
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            outcome = resolve_recommendation(
                self.team_id,
                MarketingAnalyticsRecommendationIdentity(**data["identity"]),
                MarketingAnalyticsRecommendationResolutionState(data["resolution"]),
                cast(User, request.user).id,
                name=data["name"],
            )
        except InvalidRecommendationIdentity as error:
            raise ValidationError({"identity": str(error)})
        return Response(
            RecommendationResolutionSerializer(outcome.resolution).data,
            status=status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK,
        )

    @validated_request(
        summary="Restore a recommendation",
        description="Deletes a resolution, so its recommendation shows again.",
        responses={204: OpenApiResponse(description="The resolution is deleted.")},
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            resolution_id = UUID(pk)
        except ValueError:
            raise NotFound()
        if not restore_recommendation(self.team_id, str(resolution_id)):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
