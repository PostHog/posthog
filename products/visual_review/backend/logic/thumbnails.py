"""Thumbnail lookup and reads for a snapshot identifier."""

from __future__ import annotations

from uuid import UUID

from ..models import RunSnapshot
from ..storage import ArtifactStorage


def get_thumbnail_hash_for_identifier(repo_id: UUID, identifier: str) -> str | None:
    """Look up the thumbnail content hash for a snapshot identifier.

    Finds the most recent artifact with a thumbnail for this identifier
    across all runs. Returns the thumbnail's content_hash or None.
    """
    snapshot = (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            identifier=identifier,
            current_artifact__thumbnail__isnull=False,
        )
        .select_related("current_artifact__thumbnail")
        .order_by("-run__created_at")
        .first()
    )

    if snapshot is None:
        return None

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail is None:
        return None

    return artifact.thumbnail.content_hash


def read_thumbnail_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.read(content_hash)
