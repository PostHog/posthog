"""Attaching computed diff results to a snapshot."""

from __future__ import annotations

from uuid import UUID

from ..diff_metadata import DiffMetadata
from ..facade.enums import ChangeKind, ClassificationReason, SnapshotResult
from ..models import Artifact, RunSnapshot


def update_snapshot_diff(
    snapshot_id: UUID,
    diff_percentage: float,
    diff_pixel_count: int,
    ssim_score: float,
    change_kind: ChangeKind | None,
    diff_artifact: Artifact | None = None,
    diff_metadata: DiffMetadata | None = None,
    absorbed: bool = False,
    team_id: int | None = None,
) -> RunSnapshot:
    """Attach computed diff metrics to a snapshot, in one row write.

    Serves both outcomes of the diff pipeline. A CHANGED snapshot carries a
    `change_kind`, its diff image and its metadata. A snapshot the classifier
    absorbed is UNCHANGED with no kind, and passes an artifact and metadata
    only when it has a row shift worth showing; `None` for either leaves that
    column alone rather than clearing it.

    `absorbed` flips the row to UNCHANGED / BELOW_THRESHOLD in the same save as
    the metrics. The diff pipeline retries CHANGED rows with no kind and no
    artifact, so the metrics and the terminal state must never land apart.
    """
    qs = RunSnapshot.objects.select_related("run")
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    snapshot = qs.get(id=snapshot_id)
    if snapshot.result not in (SnapshotResult.CHANGED, SnapshotResult.UNCHANGED):
        raise ValueError(f"Cannot attach diff to snapshot with result={snapshot.result}")
    snapshot.diff_percentage = diff_percentage
    snapshot.diff_pixel_count = diff_pixel_count
    snapshot.ssim_score = ssim_score
    snapshot.change_kind = change_kind.value if change_kind else ""
    update_fields = ["diff_percentage", "diff_pixel_count", "ssim_score", "change_kind"]

    if diff_artifact is not None:
        if diff_artifact.repo_id != snapshot.run.repo_id:
            raise ValueError(
                f"Cross-repo artifact reference: artifact repo {diff_artifact.repo_id} "
                f"!= snapshot repo {snapshot.run.repo_id}"
            )
        snapshot.diff_artifact = diff_artifact
        update_fields.append("diff_artifact")

    if diff_metadata is not None:
        # The Pydantic dump is the only legal write path into this column; reads
        # go through DiffMetadata.model_validate. Storage is JSONB; the schema
        # lives in diff_metadata.py.
        snapshot.diff_metadata = diff_metadata.model_dump(mode="json")
        update_fields.append("diff_metadata")

    if absorbed:
        snapshot.result = SnapshotResult.UNCHANGED
        snapshot.classification_reason = ClassificationReason.BELOW_THRESHOLD
        update_fields.extend(["result", "classification_reason"])

    snapshot.save(update_fields=update_fields)
    return snapshot
