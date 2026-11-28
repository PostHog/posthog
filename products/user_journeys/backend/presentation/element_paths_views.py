from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.mixins import ValidatedRequest, validated_request

from ..facade import api
from ..facade.contracts import ElementPathsQueryError
from .element_paths_serializers import (
    ElementPathsQuerySerializer,
    ElementPathsResultSerializer,
    element_paths_query_from,
)
from .views import UserJourneysFlagGateMixin


class _SingleResultSchema(PostHogAutoSchema):
    """Documents `list` as one result object. drf-spectacular would otherwise wrap it in an array."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class ElementPathsViewSet(UserJourneysFlagGateMixin, viewsets.GenericViewSet):
    """Most common user paths through clicks on one element."""

    # The toolbar calls this with an OAuth token that holds `query:read`. The journeys viewset is
    # session-only, so this endpoint is a separate viewset.
    scope_object = "query"
    pagination_class = None
    schema = _SingleResultSchema()

    @validated_request(
        query_serializer=ElementPathsQuerySerializer,
        responses={200: OpenApiResponse(response=ElementPathsResultSerializer)},
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Find the most common paths that sessions take before and after a click on one element."""
        try:
            result = api.get_element_paths(self.team_id, element_paths_query_from(request.validated_query_data))
        except ElementPathsQueryError as e:
            raise ValidationError({"date_from": [str(e)]})
        return Response(ElementPathsResultSerializer(instance=result).data)
