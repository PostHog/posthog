"""
DRF views for release.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.feature_flags.backend.facade.api import existing_flag_ids
from products.workflows.backend.facade.api import get_workflow_names, get_workflow_view_access

from ..facade import api, contracts
from .serializers import ReleaseSerializer, UpdateReleaseSerializer, WriteReleaseSerializer


class ReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    requires_resource_level_access = True
    serializer_class = ReleaseSerializer
    pagination_class = FacadeLimitOffsetPagination
    path_parameters = {"pk": UUID}

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        user = cast(User, request.user)
        email = None if user.anonymize_data else user.email
        enabled = api.releases_enabled(
            team_id=self.team.id,
            team_uuid=self.team.uuid,
            organization_id=self.team.organization_id,
            distinct_id=str(user.distinct_id),
            email=email,
        )
        if not enabled:
            raise PermissionDenied("Releases are not enabled for this project.")

    def _flag_visibility(self, flag_ids: list[int]) -> contracts.FlagVisibility:
        access_control = self.user_access_control
        return contracts.FlagVisibility(
            existing=frozenset(existing_flag_ids(flag_ids, team_id=self.team_id, include_deleted=True)),
            visible=frozenset(
                existing_flag_ids(flag_ids, team_id=self.team_id, access_control=access_control, include_deleted=True)
            ),
            linkable=frozenset(existing_flag_ids(flag_ids, team_id=self.team_id, access_control=access_control)),
        )

    def _broadcast_visibility(self, broadcast_ids: list[UUID]) -> contracts.BroadcastVisibility:
        requested = {str(broadcast_id): broadcast_id for broadcast_id in broadcast_ids}
        if not requested:
            return contracts.BroadcastVisibility(existing=frozenset(), visible=frozenset())
        access = get_workflow_view_access(team_id=self.team_id, user_access_control=self.user_access_control)
        names = get_workflow_names(team_id=self.team_id, workflow_ids=requested.keys())
        return contracts.BroadcastVisibility(
            existing=frozenset(
                broadcast_id for key, broadcast_id in requested.items() if key in names or key in access.blocked_ids
            ),
            visible=frozenset(broadcast_id for key, broadcast_id in requested.items() if key in access.viewable_ids),
        )

    @property
    def _lookups(self) -> api.LinkLookups:
        return api.LinkLookups(flags=self._flag_visibility, broadcasts=self._broadcast_visibility)

    @extend_schema(responses={200: ReleaseSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List the releases of the project, oldest first."""
        return facade_page_response(
            self,
            lambda page: api.list_page(self.team_id, page, self._lookups),
            serializer_class=ReleaseSerializer,
        )

    @validated_request(
        request_serializer=WriteReleaseSerializer,
        responses={201: OpenApiResponse(response=ReleaseSerializer)},
        include_serializer_context=True,
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Create a release."""
        try:
            dto = api.create(
                contracts.CreateReleaseInput(team_id=self.team_id, **request.validated_data), self._lookups
            )
        except api.UnknownFeatureFlagsError as error:
            raise ValidationError({"feature_flag_ids": f"These flags do not exist in this project: {error.flag_ids}"})
        except api.UnknownBroadcastsError as error:
            raise ValidationError(
                {"broadcast_ids": f"These broadcasts do not exist in this project: {error.broadcast_ids}"}
            )
        return Response(ReleaseSerializer(dto).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=UpdateReleaseSerializer,
        responses={200: OpenApiResponse(response=ReleaseSerializer)},
        include_serializer_context=True,
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: UUID, **kwargs) -> Response:
        """Change the name, description, owner or linked flags of a release."""
        try:
            dto = api.update(self.team_id, pk, request.validated_data, self._lookups)
        except api.ReleaseNotFoundError:
            raise NotFound("Release not found.")
        except api.UnknownFeatureFlagsError as error:
            raise ValidationError({"feature_flag_ids": f"These flags do not exist in this project: {error.flag_ids}"})
        except api.UnknownBroadcastsError as error:
            raise ValidationError(
                {"broadcast_ids": f"These broadcasts do not exist in this project: {error.broadcast_ids}"}
            )
        return Response(ReleaseSerializer(dto).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete a release. Its flags, experiments and early access features stay."""
        api.delete(self.team_id, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
