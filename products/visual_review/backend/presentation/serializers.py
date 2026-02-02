"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..api.dtos import (
    ApproveRunRequestInput,
    ApproveSnapshotInput,
    Artifact,
    CreateProjectInput,
    CreateRunInput,
    CreateRunResult,
    Project,
    Run,
    RunSummary,
    Snapshot,
    SnapshotManifestItem,
    UpdateProjectRequestInput,
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


class UpdateProjectInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = UpdateProjectRequestInput


class ApproveSnapshotInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveSnapshotInput


class ApproveRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveRunRequestInput


class CreateProjectInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateProjectInput
