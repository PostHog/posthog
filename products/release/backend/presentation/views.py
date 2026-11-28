"""
DRF views for release.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

import builtins
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
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import get_authenticator_scopes

from products.feature_flags.backend.facade.release_candidates import (
    list_release_catalog_flags,
    list_release_import_flags,
    release_flag_ids_matching,
    release_flag_labels,
)
from products.workflows.backend.facade.api import search_broadcast_summaries

from ..facade import api, contracts
from .link_lookups import ReleaseLinkVisibility
from .serializers import (
    BroadcastOptionSerializer,
    BroadcastSearchQuerySerializer,
    CatalogFlagsQuerySerializer,
    CatalogFlagsResponseSerializer,
    CatalogReleasesQuerySerializer,
    CatalogReleasesResponseSerializer,
    FlagReleasesQuerySerializer,
    FlagReleasesSerializer,
    ImportAllResponseSerializer,
    MergeReleasesSerializer,
    ReleaseSerializer,
    UpdateReleaseSerializer,
    WriteReleaseSerializer,
)

BROADCAST_SEARCH_LIMIT = 50


class ReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "broadcast_search",
        "catalog_flags",
        "catalog_releases",
        "flag_suggestions",
    ]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "import_all", "merge"]
    serializer_class = ReleaseSerializer
    pagination_class = FacadeLimitOffsetPagination
    path_parameters = {"pk": UUID}

    @property
    def requires_resource_level_access(self) -> bool:
        return self.action != "catalog_flags"

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
            for_area=self.action == "catalog_flags",
        )
        if not enabled:
            raise PermissionDenied("Releases are not enabled for this project.")

    @property
    def _visibility(self) -> ReleaseLinkVisibility:
        return ReleaseLinkVisibility(
            team=self.team, access_control=self.user_access_control, held_scopes=self._held_scopes
        )

    def _flag_visibility(self, flag_ids: list[int]) -> contracts.FlagVisibility:
        return self._visibility.flags(flag_ids)

    @property
    def _held_scopes(self) -> list[str] | None:
        return get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))

    def _can_read_workflows(self) -> bool:
        return self._visibility.can_read_workflows()

    def _flag_labels(self, flag_ids: list[int]) -> dict[int, contracts.FlagLabel]:
        return {
            flag_id: contracts.FlagLabel(id=label.id, key=label.key, name=label.name)
            for flag_id, label in release_flag_labels(team_id=self.team_id, flag_ids=flag_ids).items()
        }

    def _gets_own_release(self, flag_id: int) -> bool:
        return bool(
            list_release_import_flags(
                team_id=self.team_id, project_id=self.team.project_id, access_control=None, flag_ids=[flag_id]
            )
        )

    def _search_flags(self, terms: list[str]) -> list[int]:
        return release_flag_ids_matching(team_id=self.team_id, terms=terms, limit=api.SUGGESTION_FLAG_MATCHES)

    @property
    def _lookups(self) -> api.LinkLookups:
        return self._visibility.lookups()

    @extend_schema(responses={200: ReleaseSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List the releases of the project, oldest first."""
        return facade_page_response(
            self,
            lambda page: api.list_page(self.team_id, page, self._lookups),
            serializer_class=ReleaseSerializer,
        )

    @extend_schema(responses={200: ReleaseSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Get one release with its linked flags, broadcasts, surveys and insights."""
        try:
            dto = api.get(self.team_id, pk, self._lookups)
        except api.ReleaseNotFoundError:
            raise NotFound("Release not found.")
        return Response(ReleaseSerializer(dto).data)

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
        except api.UnknownLinkedObjectsError as error:
            raise ValidationError({error.field: f"These {error.noun} do not exist in this project: {error.ids}"})
        report_user_action(
            request.user,
            "release created",
            {"release_id": str(dto.id), "creation_source": "manual", "feature_flag_count": len(dto.feature_flag_ids)},
            team=self.team,
            organization=self.organization,
            request=request,
        )
        return Response(ReleaseSerializer(dto).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=UpdateReleaseSerializer,
        responses={200: OpenApiResponse(response=ReleaseSerializer)},
        include_serializer_context=True,
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: UUID, **kwargs) -> Response:
        """Change the name, description, owner or linked flags, broadcasts, surveys and insights of a release."""
        try:
            dto = api.update(self.team_id, pk, request.validated_data, self._lookups)
        except api.ReleaseNotFoundError:
            raise NotFound("Release not found.")
        except api.UnknownLinkedObjectsError as error:
            raise ValidationError({error.field: f"These {error.noun} do not exist in this project: {error.ids}"})
        except api.TooManyMetricsError:
            raise ValidationError(
                {
                    "metric_insight_ids": (
                        f"A release can have up to {contracts.MAX_METRICS} metrics, including ones you cannot see."
                    )
                }
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

    @validated_request(
        request_serializer=MergeReleasesSerializer,
        responses={200: OpenApiResponse(response=ReleaseSerializer)},
    )
    @action(detail=True, methods=["post"])
    def merge(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Merge other releases into this one. This release keeps its name, gains their links, then they are deleted."""
        try:
            target_id = UUID(str(pk))
        except ValueError:
            raise NotFound("Release not found.")
        source_ids = request.validated_data["release_ids"]
        try:
            dto = api.merge(
                self.team_id,
                target_id,
                source_ids,
                self._lookups,
                request.validated_data.get("name", "").strip() or None,
            )
        except api.ReleaseNotFoundError as error:
            if error.args and error.args[0] == target_id:
                raise NotFound("Release not found.")
            raise ValidationError({"release_ids": f"These releases do not exist in this project: {list(error.args)}"})
        except api.InvalidMergeError as error:
            raise ValidationError({"release_ids": str(error)})
        report_user_action(
            request.user,
            "releases merged",
            {"release_id": str(target_id), "merged_count": len(set(source_ids) - {target_id})},
            team=self.team,
            organization=self.organization,
            request=request,
        )
        return Response(ReleaseSerializer(dto).data)

    @validated_request(
        query_serializer=CatalogFlagsQuerySerializer,
        responses={200: OpenApiResponse(response=CatalogFlagsResponseSerializer)},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def catalog_flags(self, request: ValidatedRequest, **kwargs) -> Response:
        """List the project's feature flags the caller can see, newest or oldest first, with only the fields a list shows."""
        query = request.validated_query_data
        flags, has_more = list_release_catalog_flags(
            team_id=self.team_id,
            project_id=self.team.project_id,
            access_control=self.user_access_control,
            search=query.get("search", "").strip(),
            created_by_ids=query.get("created_by") or None,
            oldest_first=query["order"] == "created_at",
            limit=query["limit"],
            offset=query["offset"],
        )
        return Response(CatalogFlagsResponseSerializer({"results": flags, "has_more": has_more}).data)

    @validated_request(
        query_serializer=CatalogReleasesQuerySerializer,
        responses={200: OpenApiResponse(response=CatalogReleasesResponseSerializer)},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def catalog_releases(self, request: ValidatedRequest, **kwargs) -> Response:
        """List the project's releases, newest or oldest first, with only the fields a list shows."""
        query = request.validated_query_data
        try:
            releases, next_cursor = api.list_catalog_page(
                self.team_id,
                self._flag_visibility,
                search=query.get("search", "").strip(),
                limit=query["limit"],
                cursor=query["cursor"],
                owner_ids=query.get("owner") or None,
                oldest_first=query["order"] == "created_at",
                feature_flag_id=query.get("feature_flag_id"),
            )
        except api.InvalidCatalogCursorError:
            raise ValidationError({"cursor": "This cursor is not valid."})
        return Response(CatalogReleasesResponseSerializer({"results": releases, "next_cursor": next_cursor}).data)

    @validated_request(
        query_serializer=FlagReleasesQuerySerializer,
        responses={200: OpenApiResponse(response=FlagReleasesSerializer)},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def flag_suggestions(self, request: ValidatedRequest, **kwargs) -> Response:
        """Find the releases a feature flag is in, and the existing releases it probably belongs to."""
        flag_id = request.validated_query_data["feature_flag_id"]
        try:
            result = api.releases_for_flag(
                self.team_id,
                flag_id,
                self._flag_visibility,
                self._flag_labels,
                self._search_flags,
                self._gets_own_release,
            )
        except api.FlagNotFoundError:
            raise NotFound("Feature flag not found.")
        report_user_action(
            request.user,
            "release suggestions served",
            {"suggestion_count": len(result.suggestions), "in_release": bool(result.current)},
            team=self.team,
            organization=self.organization,
            request=request,
        )
        return Response(FlagReleasesSerializer(result).data)

    @extend_schema(request=None, responses={201: ImportAllResponseSerializer})
    @action(detail=False, methods=["post"], pagination_class=None)
    def import_all(self, request: Request, **kwargs) -> Response:
        """Set up releases for the whole project once: one per active flag. Later calls create nothing."""
        created_count = api.import_all(self.team_id, self._import_flags)
        report_user_action(
            request.user,
            "release import completed",
            {"created_count": created_count},
            team=self.team,
            organization=self.organization,
            request=request,
        )
        return Response(
            ImportAllResponseSerializer({"created_count": created_count}).data, status=status.HTTP_201_CREATED
        )

    def _import_flags(self) -> "builtins.list[api.ImportFlag]":
        return [
            api.ImportFlag(id=flag.id, key=flag.key)
            for flag in list_release_import_flags(
                team_id=self.team_id, project_id=self.team.project_id, access_control=None
            )
        ]

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete a release. Its flags, experiments and early access features stay."""
        try:
            api.delete(self.team_id, pk)
        except api.ReleaseNotFoundError:
            raise NotFound("Release not found.")
        report_user_action(
            request.user,
            "release deleted",
            {"release_id": str(pk)},
            team=self.team,
            organization=self.organization,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
