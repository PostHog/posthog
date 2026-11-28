from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict

from ..facade import api
from ..facade.contracts import (
    CreateJourneyInput,
    JourneyDeployNotFoundError,
    JourneyNotFoundError,
    JourneyNotRunnableError,
    JourneyRunInProgressError,
    JourneyRunNotFoundError,
    JourneyRunTargetNotAllowedError,
    UpdateJourneyInput,
)
from .serializers import (
    CreateJourneyInputSerializer,
    JourneyFunnelQuerySerializer,
    JourneySerializer,
    UpdateJourneyInputSerializer,
)

_NOT_FOUND_ERRORS = (JourneyNotFoundError, JourneyRunNotFoundError, JourneyDeployNotFoundError)
_INVALID_REQUEST_ERRORS = (JourneyNotRunnableError, JourneyRunTargetNotAllowedError)


class UserJourneysViewSetMixin(TeamAndOrgViewSetMixin):
    """Answers 404 while the product is off for the team, and maps facade errors to HTTP statuses."""

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not api.is_enabled(self.team_id):
            raise NotFound()

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, _NOT_FOUND_ERRORS):
            exc = NotFound()
        elif isinstance(exc, _INVALID_REQUEST_ERRORS):
            exc = ValidationError({"detail": str(exc)})
        elif isinstance(exc, JourneyRunInProgressError):
            exc = Conflict(str(exc))
        return super().handle_exception(exc)


class JourneyViewSet(UserJourneysViewSetMixin, viewsets.GenericViewSet):
    """Saved user flows that PostHog measures as funnels."""

    # Session access only until the product is released and has its own API scope.
    scope_object = "INTERNAL"
    path_parameters = {"pk": UUID}
    pagination_class = FacadeLimitOffsetPagination

    @extend_schema(responses={200: JourneySerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the project's journeys, newest first, each with its latest run."""
        return facade_page_response(
            self, lambda page: api.list_journeys(self.team_id, page), serializer_class=JourneySerializer
        )

    @validated_request(
        request_serializer=CreateJourneyInputSerializer,
        responses={201: OpenApiResponse(response=JourneySerializer)},
    )
    def create(self, request: TypedRequest[CreateJourneyInput], **kwargs: Any) -> Response:
        """Create a journey."""
        journey = api.create_journey(self.team_id, request.user.id, request.validated_data)
        return Response(JourneySerializer(instance=journey).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: JourneySerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        """Get a journey."""
        return Response(JourneySerializer(instance=api.get_journey(self.team_id, pk)).data)

    @validated_request(
        request_serializer=UpdateJourneyInputSerializer,
        responses={200: OpenApiResponse(response=JourneySerializer)},
    )
    def partial_update(self, request: TypedRequest[UpdateJourneyInput], pk: UUID, **kwargs: Any) -> Response:
        """Change some fields of a journey."""
        journey = api.update_journey(self.team_id, pk, request.validated_data)
        return Response(JourneySerializer(instance=journey).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        """Delete a journey."""
        api.delete_journey(self.team_id, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: JourneyFunnelQuerySerializer})
    @action(detail=True, methods=["GET"], url_path="funnel_query", pagination_class=None)
    def funnel_query(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        """Get the funnel query that measures how many sessions complete the journey."""
        query = api.journey_to_funnels_query(api.get_journey(self.team_id, pk))
        return Response(
            JourneyFunnelQuerySerializer(instance={"query": query.model_dump(mode="json", exclude_none=True)}).data
        )
