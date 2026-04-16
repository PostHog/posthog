"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    AddSnapshotsInput,
    AddSnapshotsResult,
    ApproveRunRequestInput,
    ApproveSnapshotInput,
    Artifact,
    AutoApproveResult,
    CreateRepoInput,
    CreateRunInput,
    CreateRunResult,
    Repo,
    Run,
    RunSummary,
    Snapshot,
    SnapshotHistoryEntry,
    SnapshotManifestItem,
    ToleratedHashEntry,
    UpdateRepoRequestInput,
    UploadTarget,
)

# --- Output Serializers ---


class ReviewStateCountsSerializer(serializers.Serializer):
    needs_review = serializers.IntegerField()
    clean = serializers.IntegerField()
    processing = serializers.IntegerField()
    stale = serializers.IntegerField()


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


class RepoSerializer(DataclassSerializer):
    class Meta:
        dataclass = Repo


class UploadTargetSerializer(DataclassSerializer):
    class Meta:
        dataclass = UploadTarget


class CreateRunResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunResult


class AutoApproveResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = AutoApproveResult


# --- Input Serializers ---


class SnapshotManifestItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = SnapshotManifestItem


class CreateRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunInput


class AddSnapshotsInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = AddSnapshotsInput


class AddSnapshotsResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = AddSnapshotsResult


class UpdateRepoInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = UpdateRepoRequestInput


class ApproveSnapshotInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveSnapshotInput


class ApproveRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApproveRunRequestInput


class SnapshotHistoryEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = SnapshotHistoryEntry


class ToleratedHashEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = ToleratedHashEntry


class MarkToleratedInputSerializer(serializers.Serializer):
    snapshot_id = serializers.UUIDField()


class CreateRepoInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRepoInput
