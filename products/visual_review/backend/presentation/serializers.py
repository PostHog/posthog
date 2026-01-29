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
    UploadTarget,
)

# --- Output Serializers ---


class RunSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = RunSummary


class ArtifactSerializer(DataclassSerializer):
    class Meta:
        dataclass = Artifact


class SnapshotSerializer(DataclassSerializer):
    # Explicitly mark artifact fields as nullable for OpenAPI schema
    current_artifact = ArtifactSerializer(allow_null=True, required=False)
    baseline_artifact = ArtifactSerializer(allow_null=True, required=False)
    diff_artifact = ArtifactSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = Snapshot


class RunSerializer(DataclassSerializer):
    class Meta:
        dataclass = Run


class ProjectSerializer(DataclassSerializer):
    class Meta:
        dataclass = Project


class UploadTargetSerializer(DataclassSerializer):
    class Meta:
        dataclass = UploadTarget


class CreateRunResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunResult


# --- Input Serializers ---


class SnapshotManifestItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = SnapshotManifestItem


class CreateRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunInput


class UpdateProjectInputSerializer(serializers.Serializer):
    """Input for updating a project. project_id comes from URL."""

    name = serializers.CharField(max_length=255, required=False, allow_null=True)
    repo_full_name = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    baseline_file_paths = serializers.DictField(
        child=serializers.CharField(max_length=512),
        required=False,
        allow_null=True,
    )


class ApproveSnapshotInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveSnapshotInput


class ApproveRunInputSerializer(serializers.Serializer):
    """Input for approving a run."""

    snapshots = ApproveSnapshotInputSerializer(many=True)
    commit_to_github = serializers.BooleanField(default=True, required=False)
