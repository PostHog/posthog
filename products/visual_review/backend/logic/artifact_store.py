"""Artifact rows and their object-storage bytes."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from uuid import UUID

from django.db import models as db_models

from ..models import Artifact, Repo, RunSnapshot
from ..storage import ArtifactStorage

ARTIFACT_HASH_BATCH_SIZE = 500


def _iter_batches(values: Iterable[str], batch_size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def get_artifact(repo_id: UUID, content_hash: str) -> Artifact | None:
    return Artifact.objects.filter(repo_id=repo_id, content_hash=content_hash).first()


def get_or_create_artifact(
    repo_id: UUID,
    content_hash: str,
    storage_path: str,
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
    team_id: int | None = None,
) -> tuple[Artifact, bool]:
    # Resolve team_id from the repo when not provided by the caller.
    if team_id is None:
        # nosemgrep: idor-lookup-without-team — resolving team_id from repo
        team_id = Repo.objects.values_list("team_id", flat=True).get(id=repo_id)

    return Artifact.objects.get_or_create(
        repo_id=repo_id,
        content_hash=content_hash,
        team_id=team_id,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
        },
    )


def find_missing_hashes(repo_id: UUID, hashes: list[str]) -> list[str]:
    """Return hashes that don't exist as artifacts in the repo."""
    existing: set[str] = set()
    for hash_batch in _iter_batches(hashes, ARTIFACT_HASH_BATCH_SIZE):
        existing.update(
            Artifact.objects.filter(repo_id=repo_id, content_hash__in=hash_batch).values_list("content_hash", flat=True)
        )
    return [h for h in hashes if h not in existing]


def get_presigned_upload_url(repo_id: UUID, content_hash: str) -> dict | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.get_presigned_upload_url(content_hash)


def get_presigned_download_url(repo_id: UUID, content_hash: str) -> str | None:
    storage = ArtifactStorage(str(repo_id))
    return storage.get_presigned_download_url(content_hash)


def read_artifact_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    """Read artifact content from storage."""
    storage = ArtifactStorage(str(repo_id))
    return storage.read(content_hash)


def write_artifact_bytes(
    repo_id: UUID,
    content_hash: str,
    content: bytes,
    width: int | None = None,
    height: int | None = None,
    team_id: int | None = None,
) -> Artifact:
    """
    Write artifact content to storage and create DB record.
    Used for server-generated artifacts like diff images.
    """
    storage = ArtifactStorage(str(repo_id))
    storage_path = storage.write(content_hash, content)

    # Resolve team_id from the repo when not provided by the caller.
    if team_id is None:
        # nosemgrep: idor-lookup-without-team — resolving team_id from repo
        team_id = Repo.objects.values_list("team_id", flat=True).get(id=repo_id)

    artifact, _ = Artifact.objects.get_or_create(
        repo_id=repo_id,
        content_hash=content_hash,
        team_id=team_id,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": len(content),
        },
    )
    return artifact


def link_artifacts_to_snapshots(repo_id: UUID, content_hashes: set[str], *, run_id: UUID | None = None) -> int:
    """
    After artifacts are uploaded, link them to any pending snapshots.

    Returns number of snapshots updated.
    """
    if not content_hashes:
        return 0

    updated = 0
    for hash_batch in _iter_batches(content_hashes, ARTIFACT_HASH_BATCH_SIZE):
        artifact_id = Artifact.objects.filter(
            repo_id=repo_id,
            content_hash=db_models.OuterRef("current_hash"),
        ).values("id")[:1]
        current_snapshots = RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            current_hash__in=hash_batch,
            current_artifact__isnull=True,
        )
        if run_id is not None:
            current_snapshots = current_snapshots.filter(run_id=run_id)
        updated += current_snapshots.update(current_artifact_id=db_models.Subquery(artifact_id))

        artifact_id = Artifact.objects.filter(
            repo_id=repo_id,
            content_hash=db_models.OuterRef("baseline_hash"),
        ).values("id")[:1]
        baseline_snapshots = RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            baseline_hash__in=hash_batch,
            baseline_artifact__isnull=True,
        )
        if run_id is not None:
            baseline_snapshots = baseline_snapshots.filter(run_id=run_id)
        updated += baseline_snapshots.update(baseline_artifact_id=db_models.Subquery(artifact_id))

    return updated


def link_artifact_to_snapshots(repo_id: UUID, content_hash: str) -> int:
    return link_artifacts_to_snapshots(repo_id, {content_hash})
