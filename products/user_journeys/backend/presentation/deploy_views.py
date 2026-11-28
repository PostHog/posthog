from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter
from posthog.auth import ProjectSecretAPIKeyAuthentication

from ..facade import api
from ..facade.contracts import CreateJourneyDeployInput, JourneyRunTargetNotAllowedError
from .deploy_serializers import CreateJourneyDeploySerializer, JourneyDeployDetailSerializer, JourneyDeploySerializer
from .deploy_throttles import (
    JourneyDeployCreateRateThrottle,
    JourneyDeployCreateTeamRateThrottle,
    JourneyDeployReadRateThrottle,
    JourneyDeployReadTeamRateThrottle,
)
from .views import UserJourneysViewSetMixin


class JourneyDeployViewSet(UserJourneysViewSetMixin, viewsets.GenericViewSet):
    """Deploys that CI announces, each of which runs the project's journeys against the new build."""

    scope_object = "user_journey"
    # Extends the default authenticators. TeamAndOrgViewSetMixin keeps session, personal key and OAuth.
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["list", "retrieve", "create"]
    path_parameters = {"pk": PathParameter(type=UUID, description="A UUID string identifying the deploy.")}
    pagination_class = FacadeLimitOffsetPagination

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            limits: list[BaseThrottle] = [JourneyDeployCreateRateThrottle(), JourneyDeployCreateTeamRateThrottle()]
        else:
            limits = [JourneyDeployReadRateThrottle(), JourneyDeployReadTeamRateThrottle()]
        return [*super().get_throttles(), *limits]

    @extend_schema(responses={200: JourneyDeploySerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the project's deploys, newest deploy time first, each with the verdict on its runs."""
        return facade_page_response(
            self, lambda page: api.list_deploys(self.team_id, page), serializer_class=JourneyDeploySerializer
        )

    @extend_schema(responses={200: JourneyDeployDetailSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        """Get a deploy with the verdict on its runs. Poll it until `status` is neither `pending` nor `running`."""
        return Response(JourneyDeployDetailSerializer(instance=api.get_deploy(self.team_id, pk)).data)

    @validated_request(
        request_serializer=CreateJourneyDeploySerializer,
        responses={
            201: OpenApiResponse(response=JourneyDeployDetailSerializer, description="The deploy was recorded."),
            200: OpenApiResponse(
                response=JourneyDeployDetailSerializer,
                description="A deploy of the same commit and base URL was recorded moments ago. It is returned, "
                "and no new runs started.",
            ),
        },
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Record a deploy and start a run of the project's journeys against it. The runs finish in the background."""
        data = request.validated_data
        deploy_input = CreateJourneyDeployInput(
            commit_sha=data["commit_sha"],
            branch=data.get("branch"),
            base_url=data.get("base_url"),
            deployed_at=data.get("deployed_at"),
            journey_ids=data.get("journey_ids"),
            label=data.get("label"),
            url=data.get("url"),
            # A project secret API key authenticates as a synthetic user without an ID.
            created_by_id=request.user.id,
        )
        try:
            recorded = api.create_deploy(self.team_id, deploy_input)
        except JourneyRunTargetNotAllowedError as e:
            raise ValidationError({"base_url": [str(e)]})
        return Response(
            JourneyDeployDetailSerializer(instance=recorded.deploy).data,
            status=status.HTTP_201_CREATED if recorded.created else status.HTTP_200_OK,
        )
