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
    QuarantinedIdentifierEntry,
    QuarantineInput,
    RecomputeResult,
    Repo,
    Run,
    RunSummary,
    Snapshot,
    SnapshotHistoryEntry,
    SnapshotManifestItem,
    ToleratedHashEntry,
    UpdateRepoRequestInput,
    UploadTarget,
    UserBasicInfo,
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


class UserBasicInfoSerializer(DataclassSerializer):
    class Meta:
        dataclass = UserBasicInfo


class SnapshotSerializer(DataclassSerializer):
    # Explicitly mark artifact fields as nullable for OpenAPI schema
    current_artifact = ArtifactSerializer(allow_null=True, required=False)
    baseline_artifact = ArtifactSerializer(allow_null=True, required=False)
    diff_artifact = ArtifactSerializer(allow_null=True, required=False)
    reviewed_by = UserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = Snapshot


class RunSerializer(DataclassSerializer):
    approved_by = UserBasicInfoSerializer(allow_null=True, required=False)

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


class RecomputeResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = RecomputeResult


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
    current_artifact = ArtifactSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = SnapshotHistoryEntry


class ToleratedHashEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = ToleratedHashEntry


class MarkToleratedInputSerializer(serializers.Serializer):
    snapshot_id = serializers.UUIDField()


class QuarantinedIdentifierEntrySerializer(DataclassSerializer):
    created_by = UserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = QuarantinedIdentifierEntry


class QuarantineInputSerializer(DataclassSerializer):
    identifier = serializers.CharField(max_length=512)
    reason = serializers.CharField(max_length=255)

    class Meta:
        dataclass = QuarantineInput


class UnquarantineQuerySerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=512, help_text="Snapshot identifier to unquarantine")


class CreateRepoInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRepoInput
