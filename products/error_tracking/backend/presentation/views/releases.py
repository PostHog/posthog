from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    contracts,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade

MAX_HASH_ID_LENGTH = 128
RELEASE_HASH_IN_USE_ERROR_CODE = "release_hash_in_use"


@extend_schema_field({"type": "object", "additionalProperties": True, "nullable": True})
class ReleaseMetadataField(serializers.JSONField):
    pass


class ErrorTrackingReleaseSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingRelease


class ErrorTrackingReleaseCreateRequestSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="Human-readable release version, e.g. a semver string or build number.")
    project = serializers.CharField(help_text="Identifier of the project this release belongs to.")
    hash_id = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_HASH_ID_LENGTH,
        help_text="Optional client-supplied release hash (e.g. a git commit SHA). Generated server-side when omitted.",
    )
    metadata = ReleaseMetadataField(
        required=False, allow_null=True, help_text="Optional free-form metadata object stored alongside the release."
    )


class ErrorTrackingReleaseUpdateRequestSerializer(serializers.Serializer):
    version = serializers.CharField(
        required=False, allow_null=True, help_text="Human-readable release version. Omit to preserve the current value."
    )
    project = serializers.CharField(
        required=False, allow_null=True, help_text="Project identifier. Omit to preserve the current value."
    )
    hash_id = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_HASH_ID_LENGTH,
        help_text="Release hash (e.g. a git commit SHA). Omit to preserve the current value.",
    )
    metadata = ReleaseMetadataField(
        required=False, allow_null=True, help_text="Free-form metadata object. Omit to preserve the current value."
    )


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
        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: error_tracking_api.list_releases(self.team.id, limit=limit, offset=offset),
        )

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        release = error_tracking_api.get_release(self.team.id, pk)
        if release is None:
            raise NotFound()
        return Response(self.get_serializer(release).data)

    @extend_schema(
        request=ErrorTrackingReleaseCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingReleaseSerializer)},
    )
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
            raise ValidationError(f"Hash id {err} already in use", code=RELEASE_HASH_IN_USE_ERROR_CODE) from err
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
            raise ValidationError(f"Hash id {err} already in use", code=RELEASE_HASH_IN_USE_ERROR_CODE) from err
        if release is None:
            raise NotFound()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=ErrorTrackingReleaseUpdateRequestSerializer, responses={204: None})
    def update(self, request, *args, pk=None, **kwargs) -> Response:
        return self._apply_update(pk, request.data)

    @extend_schema(request=ErrorTrackingReleaseUpdateRequestSerializer, responses={204: None})
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
