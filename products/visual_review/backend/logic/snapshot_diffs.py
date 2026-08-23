"""Attaching computed diff results to a snapshot."""

from __future__ import annotations

from uuid import UUID

from ..diff_metadata import DiffMetadata
from ..facade.enums import ChangeKind, SnapshotResult
from ..models import Artifact, RunSnapshot


def update_snapshot_diff(
    snapshot_id: UUID,
    diff_artifact: Artifact,
    diff_percentage: float,
    diff_pixel_count: int,
    ssim_score: float,
    change_kind: ChangeKind,
    diff_metadata: DiffMetadata,
    team_id: int | None = None,
) -> RunSnapshot:
    qs = RunSnapshot.objects.select_related("run")
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    snapshot = qs.get(id=snapshot_id)
    if diff_artifact.repo_id != snapshot.run.repo_id:
        raise ValueError(
            f"Cross-repo artifact reference: artifact repo {diff_artifact.repo_id} "
            f"!= snapshot repo {snapshot.run.repo_id}"
        )
    if snapshot.result != SnapshotResult.CHANGED:
        raise ValueError(f"Cannot attach diff to snapshot with result={snapshot.result}, expected 'changed'")
    snapshot.diff_artifact = diff_artifact
    snapshot.diff_percentage = diff_percentage
    snapshot.diff_pixel_count = diff_pixel_count
    snapshot.ssim_score = ssim_score
    snapshot.change_kind = change_kind.value
    # The Pydantic dump is the only legal write path into this column; reads
    # go through DiffMetadata.model_validate. Storage is JSONB; the schema
    # lives in diff_metadata.py.
    snapshot.diff_metadata = diff_metadata.model_dump(mode="json")
    snapshot.save(
        update_fields=[
            "diff_artifact",
            "diff_percentage",
            "diff_pixel_count",
            "ssim_score",
            "change_kind",
            "diff_metadata",
        ]
    )
    return snapshot
