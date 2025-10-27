from django.shortcuts import get_object_or_404

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.utils import UUIDT

from products.error_tracking.backend.models import ErrorTrackingRelease

logger = structlog.get_logger(__name__)


class ErrorTrackingReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingRelease
        fields = ["id", "hash_id", "team_id", "created_at", "metadata", "version", "project"]
        read_only_fields = ["team_id"]


class ErrorTrackingReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingRelease.objects.all()
    scope_object_read_actions = ["list", "retrieve", "by_hash"]
    serializer_class = ErrorTrackingReleaseSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id)

        return queryset

    def validate_hash_id(self, hash_id: str, assert_new: bool) -> str:
        if len(hash_id) > 128:
            raise ValidationError("Hash id length cannot exceed 128 bytes")

        if assert_new and ErrorTrackingRelease.objects.filter(team=self.team, hash_id=hash_id).exists():
            raise ValidationError(f"Hash id {hash_id} already in use")

        return hash_id

    def update(self, request, *args, **kwargs) -> Response:
        release = self.get_object()

        metadata = request.data.get("metadata")
        hash_id = request.data.get("hash_id")
        version = request.data.get("version")
        project = request.data.get("project")

        if metadata:
            release.metadata = metadata

        if version:
            version = str(version)
            release.version = version

        if project:
            project = str(project)
            release.project = project

        if hash_id and hash_id != release.hash_id:
            hash_id = str(hash_id)
            hash_id = self.validate_hash_id(hash_id, True)
            release.hash_id = hash_id

        release.save()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        id = UUIDT()  # We use this in the hash if one isn't set, and also as the id of the model
        metadata = request.data.get("metadata")
        hash_id = str(request.data.get("hash_id") or id)
        hash_id = self.validate_hash_id(hash_id, True)
        version = request.data.get("version")
        project = request.data.get("project")

        if not version:
            raise ValidationError("Version is required")

        if not project:
            raise ValidationError("Project is required")

        version = str(version)

        release = ErrorTrackingRelease.objects.create(
            id=id, team=self.team, hash_id=hash_id, metadata=metadata, project=project, version=version
        )

        serializer = ErrorTrackingReleaseSerializer(release)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="hash/(?P<hash_id>[^/.]+)")
    def by_hash(self, request, hash_id=None, **kwargs):
        obj = get_object_or_404(self.get_queryset(), hash_id=hash_id)
        serializer = self.get_serializer(obj)
        return Response(serializer.data)
