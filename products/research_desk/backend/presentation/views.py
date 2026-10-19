"""
DRF views for research_desk.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from ..facade import api, contracts
from ..facade.enums import SourceKind
from .serializers import (
    ContactCheckQuerySerializer,
    ContactCheckResultSerializer,
    CreateResearchSourceSerializer,
    ListResearchSessionsQuerySerializer,
    ResearchSessionSerializer,
    ResearchSourceSerializer,
    UpdateResearchSourceSerializer,
)

RESEARCH_DESK_FEATURE_FLAG = "research-desk"


class _ResearchDeskViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # A real scope rather than INTERNAL so agents can reach these endpoints over MCP.
    # The feature flag keeps the product limited to PostHog staff.
    scope_object = "research_desk"
    posthog_feature_flag = RESEARCH_DESK_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    pagination_class = None


class ResearchSourceViewSet(_ResearchDeskViewSet):
    @extend_schema(responses={200: ResearchSourceSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List recruiting sources whose events count as research touches."""
        return Response(ResearchSourceSerializer(api.list_sources(), many=True).data)

    @validated_request(
        request_serializer=CreateResearchSourceSerializer,
        responses={201: OpenApiResponse(response=ResearchSourceSerializer)},
    )
    def create(self, request: Request, **kwargs) -> Response:
        """Register a workflow, survey, cohort, or event as a recruiting source."""
        data = request.validated_data
        try:
            source = api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team_id,
                    kind=SourceKind(data["kind"]),
                    external_id=data["external_id"],
                    label=data["label"],
                    owner_email=data["owner_email"],
                    product_area=data["product_area"],
                )
            )
        except contracts.ResearchSourceAlreadyExistsError as e:
            raise ValidationError({"external_id": str(e)})
        return Response(ResearchSourceSerializer(source).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)])
    @validated_request(
        request_serializer=UpdateResearchSourceSerializer,
        responses={200: OpenApiResponse(response=ResearchSourceSerializer)},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        """Update a source's label, owner, product area, or active state."""
        data = request.validated_data
        try:
            source = api.update_source(
                UUID(pk),
                contracts.UpdateResearchSourceInput(
                    label=data.get("label"),
                    owner_email=data.get("owner_email"),
                    product_area=data.get("product_area"),
                    active=data.get("active"),
                ),
            )
        except (ValueError, contracts.ResearchSourceNotFoundError):
            raise NotFound("Source not found.")
        return Response(ResearchSourceSerializer(source).data)


class ResearchSessionViewSet(_ResearchDeskViewSet):
    @validated_request(
        query_serializer=ListResearchSessionsQuerySerializer,
        responses={200: OpenApiResponse(response=ResearchSessionSerializer(many=True))},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """List customer research sessions, ordered by start time, up to 500 per request."""
        query = request.validated_query_data
        sessions = api.list_sessions(start_after=query.get("start_after"), start_before=query.get("start_before"))
        return Response(ResearchSessionSerializer(sessions, many=True).data)


class ContactCheckViewSet(_ResearchDeskViewSet):
    @validated_request(
        query_serializer=ContactCheckQuerySerializer,
        responses={200: OpenApiResponse(response=ContactCheckResultSerializer)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """Check whether PostHog recently contacted these people or this company for research.

        Returns every research touch found across registered sources and detected sessions.
        A warning is advice: anyone can still reach out.
        """
        query = request.validated_query_data
        result = api.check_contact(
            contracts.ContactCheckInput(
                team_id=self.team_id,
                emails=tuple(query["emails"]),
                domain=query.get("domain") or None,
                lookback_days=query["lookback_days"],
                warn_within_days=query["warn_within_days"],
            )
        )
        return Response(ContactCheckResultSerializer(result).data)
