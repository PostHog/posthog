"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..api.dtos import (
    ApproveSnapshotInput,
    Artifact,
    CreateRunInput,
    CreateRunResult,
    Project,
    Run,
    RunSummary,
    Snapshot,
    SnapshotManifestItem,
    UploadUrl,
)

# --- Output Serializers ---


class RunSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = RunSummary


class ArtifactSerializer(DataclassSerializer):
    class Meta:
        dataclass = Artifact


class SnapshotSerializer(DataclassSerializer):
    class Meta:
        dataclass = Snapshot


class RunSerializer(DataclassSerializer):
    class Meta:
        dataclass = Run


class ProjectSerializer(DataclassSerializer):
    class Meta:
        dataclass = Project


class CreateRunResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunResult


class UploadUrlSerializer(DataclassSerializer):
    class Meta:
        dataclass = UploadUrl


# --- Input Serializers ---


class SnapshotManifestItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = SnapshotManifestItem


class CreateRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunInput


class ApproveSnapshotInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveSnapshotInput


class ApproveRunInputSerializer(serializers.Serializer):
    """Input for approving a run."""

    snapshots = ApproveSnapshotInputSerializer(many=True)


# --- Convenience Serializers ---


class UploadUrlRequestSerializer(serializers.Serializer):
    """Request for a presigned upload URL."""

    content_hash = serializers.CharField(max_length=128)


class ArtifactUploadedSerializer(serializers.Serializer):
    """Notification that an artifact has been uploaded."""

    content_hash = serializers.CharField(max_length=128)
    width = serializers.IntegerField(required=False, allow_null=True)
    height = serializers.IntegerField(required=False, allow_null=True)
    size_bytes = serializers.IntegerField(required=False, allow_null=True)
