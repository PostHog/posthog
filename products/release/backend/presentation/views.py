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

from posthog.api.mixins import TypedRequest, ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.feature_flags.backend.facade.api import existing_flag_ids
from products.workflows.backend.facade.api import (
    get_recent_batch_jobs,
    get_workflow_summaries,
    get_workflow_view_access,
    search_broadcast_summaries,
)
from products.workflows.backend.facade.contracts import WorkflowSummary

from ..facade import api, contracts
from .serializers import (
    BroadcastOptionSerializer,
    BroadcastSearchQuerySerializer,
    ReleaseSerializer,
    UpdateReleaseSerializer,
    WriteReleaseSerializer,
)

RECENT_SENDS_LIMIT = 20
BROADCAST_SEARCH_LIMIT = 50


class ReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    requires_resource_level_access = True
    scope_object_read_actions = ["list", "retrieve", "broadcast_search"]
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
            return contracts.BroadcastVisibility(existing=frozenset(), visible=frozenset(), linkable=frozenset())
        if not self._can_read_workflows():
            return contracts.BroadcastVisibility(
                existing=frozenset(requested.values()), visible=frozenset(), linkable=frozenset()
            )
        access = get_workflow_view_access(
            team_id=self.team_id, user_access_control=self.user_access_control, workflow_ids=requested.keys()
        )
        names = {
            summary.id: summary
            for summary in get_workflow_summaries(team_id=self.team_id, workflow_ids=requested.keys())
        }
        return contracts.BroadcastVisibility(
            existing=frozenset(requested.values()),
            visible=frozenset(broadcast_id for key, broadcast_id in requested.items() if access.allows(key)),
            linkable=frozenset(
                broadcast_id for key, broadcast_id in requested.items() if key in names and key in access.viewable_ids
            ),
            summaries=self._broadcast_summaries(
                {key: broadcast_id for key, broadcast_id in requested.items() if key in names and access.allows(key)},
                names,
            ),
        )

    def _can_read_workflows(self) -> bool:
        held = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        return held is None or "*" in held or not scopes_not_covered(held, ["hog_flow:read"])

    def _broadcast_summaries(
        self, shown: dict[str, UUID], names: dict[str, WorkflowSummary]
    ) -> tuple[contracts.LinkedBroadcastDTO, ...]:
        sends = get_recent_batch_jobs(team_id=self.team_id, workflow_ids=shown.keys(), limit=RECENT_SENDS_LIMIT)
        return tuple(
            contracts.LinkedBroadcastDTO(
                id=broadcast_id,
                name=names[key].name,
                status=names[key].status,
                recent_sends=[
                    contracts.LinkedSendDTO(id=job.id, status=job.status, created_at=job.created_at)
                    for job in sends.get(key, [])
                ],
            )
            for key, broadcast_id in shown.items()
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

    @validated_request(
        query_serializer=BroadcastSearchQuerySerializer,
        responses={200: OpenApiResponse(response=BroadcastOptionSerializer(many=True))},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def broadcast_search(self, request: ValidatedRequest, **kwargs) -> Response:
        """Search the broadcasts a release can link, returning only their ID, name and status."""
        if not self._can_read_workflows():
            return Response([])
        options = search_broadcast_summaries(
            team_id=self.team_id,
            search=request.validated_query_data.get("search", ""),
            user_access_control=self.user_access_control,
            limit=BROADCAST_SEARCH_LIMIT,
        )
        return Response(BroadcastOptionSerializer(options, many=True).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete a release. Its flags, experiments and early access features stay."""
        api.delete(self.team_id, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
