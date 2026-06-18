from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)

MAX_HASH_ID_LENGTH = 128


class ErrorTrackingReleaseSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingRelease


class ErrorTrackingReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve", "by_hash"]
    serializer_class = ErrorTrackingReleaseSerializer

    def _validated_hash_id(self, hash_id) -> str | None:
        if not hash_id:
            return None
        hash_id = str(hash_id)
        if len(hash_id) > MAX_HASH_ID_LENGTH:
            raise ValidationError("Hash id length cannot exceed 128 bytes")
        return hash_id

    def list(self, request, *args, **kwargs) -> Response:
        releases = error_tracking_api.list_releases(self.team.id)
        page = self.paginate_queryset(releases)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(releases, many=True).data)

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        release = error_tracking_api.get_release(self.team.id, pk)
        if release is None:
            raise NotFound()
        return Response(self.get_serializer(release).data)

    def create(self, request, *args, **kwargs) -> Response:
        version = request.data.get("version")
        project = request.data.get("project")
        if not version:
            raise ValidationError("Version is required")
        if not project:
            raise ValidationError("Project is required")
        hash_id = self._validated_hash_id(request.data.get("hash_id"))
        try:
            release = error_tracking_api.create_release(
                self.team.id,
                version=str(version),
                project=str(project),
                hash_id=hash_id,
                metadata=request.data.get("metadata"),
            )
        except error_tracking_api.ReleaseHashInUseError as err:
            raise ValidationError(f"Hash id {err} already in use")
        return Response(self.get_serializer(release).data, status=status.HTTP_201_CREATED)

    def _apply_update(self, pk: str, data) -> Response:
        hash_id = self._validated_hash_id(data.get("hash_id"))
        try:
            release = error_tracking_api.update_release(
                self.team.id,
                pk,
                metadata=data.get("metadata"),
                hash_id=hash_id,
                version=data.get("version"),
                project=data.get("project"),
            )
        except error_tracking_api.ReleaseHashInUseError as err:
            raise ValidationError(f"Hash id {err} already in use")
        if release is None:
            raise NotFound()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def update(self, request, *args, pk=None, **kwargs) -> Response:
        return self._apply_update(pk, request.data)

    def partial_update(self, request, *args, pk=None, **kwargs) -> Response:
        return self._apply_update(pk, request.data)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_release(self.team.id, pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="hash/(?P<hash_id>[^/.]+)")
    def by_hash(self, request, hash_id=None, **kwargs) -> Response:
        release = error_tracking_api.get_release_by_hash(self.team.id, hash_id)
        if release is None:
            raise NotFound()
        return Response(self.get_serializer(release).data)
