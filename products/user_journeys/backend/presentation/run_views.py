from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter
from posthog.auth import ProjectSecretAPIKeyAuthentication

from ..facade import api
from ..facade.contracts import CreateJourneyRunInput
from ..facade.enums import JourneyRunTrigger
from .deploy_throttles import JourneyDeployReadRateThrottle, JourneyDeployReadTeamRateThrottle
from .run_serializers import CreateJourneyRunSerializer, JourneyRunDetailSerializer, JourneyRunSerializer
from .views import UserJourneysViewSetMixin


class JourneyRunViewSet(UserJourneysViewSetMixin, viewsets.GenericViewSet):
    """Replays of a journey in a headless browser, with a verdict and a screenshot for each step."""

    scope_object = "user_journey"
    # Tokens may read runs, so CI can follow a deploy's run to its steps. Starting a run stays with a
    # logged-in person: an action in neither list needs a session.
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions: list[str] = []
    # Extends the default authenticators. TeamAndOrgViewSetMixin keeps session, personal key and OAuth.
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["list", "retrieve"]
    path_parameters = {
        "journey_id": PathParameter(type=UUID, description="A UUID string identifying the journey."),
        "pk": PathParameter(type=UUID, description="A UUID string identifying the run."),
    }
    pagination_class = FacadeLimitOffsetPagination

    @property
    def journey_id(self) -> UUID:
        return self.kwargs["parent_lookup_journey_id"]

    def get_throttles(self) -> list[BaseThrottle]:
        return [*super().get_throttles(), JourneyDeployReadRateThrottle(), JourneyDeployReadTeamRateThrottle()]

    @extend_schema(responses={200: JourneyRunSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the journey's runs, newest first. Steps are left out; get a run to see them."""
        return facade_page_response(
            self,
            lambda page: api.list_runs(self.team_id, self.journey_id, page),
            serializer_class=JourneyRunSerializer,
        )

    @extend_schema(responses={200: JourneyRunDetailSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        """Get a run with each step's verdict and screenshot URLs."""
        return Response(JourneyRunDetailSerializer(instance=api.get_run(self.team_id, self.journey_id, pk)).data)

    @validated_request(
        request_serializer=CreateJourneyRunSerializer,
        responses={202: OpenApiResponse(response=JourneyRunSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Start a run of the journey now. The run starts as pending and finishes in the background."""
        data = request.validated_data
        run = api.start_run(
            self.team_id,
            CreateJourneyRunInput(
                journey_id=self.journey_id,
                trigger=JourneyRunTrigger.MANUAL,
                base_url=data.get("base_url"),
                commit_sha=data.get("commit_sha"),
                branch=data.get("branch"),
                created_by_id=request.user.id,
                viewport_width=data["viewport_width"],
                viewport_height=data["viewport_height"],
            ),
        )
        return Response(JourneyRunSerializer(instance=run).data, status=status.HTTP_202_ACCEPTED)
