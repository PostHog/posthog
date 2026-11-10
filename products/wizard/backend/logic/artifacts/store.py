from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils.dateparse import parse_datetime

from posthog.dataclasses import frozen

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import (
    WizardPullRequestState,
    WizardRunArtifactType,
    WizardRunEnvironment,
    WizardWorkspaceType,
)
from products.wizard.backend.logic.artifacts.mappers import pull_request_metadata_to_record, record_to_artifact
from products.wizard.backend.models import WizardRun, WizardRunArtifact


@frozen
class StoredGitDiffArtifact:
    storage_path: str
    content_hash: str
    size_bytes: int


@frozen
class PullRequestOwner:
    team_id: int
    run_id: UUID
    # None when the run is known but its pull request artifact is not stored yet.
    artifact_id: UUID | None


def upsert_git_diff(
    *,
    team_id: int,
    run_id: UUID,
    storage_path: str,
    size_bytes: int,
    content_hash: str,
    additions: int,
    removals: int,
) -> WizardRunGitDiffArtifactDTO:
    with transaction.atomic():
        WizardRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        artifact, _ = WizardRunArtifact.objects.for_team(team_id).update_or_create(
            run_id=run_id,
            type=WizardRunArtifactType.GIT_DIFF.value,
            defaults={
                "team_id": team_id,
                "storage_path": storage_path,
                "external_url": None,
                "metadata": {"additions": additions, "removals": removals},
                "size_bytes": size_bytes,
                "content_hash": content_hash,
            },
        )

    result = record_to_artifact(artifact)

    if not isinstance(result, WizardRunGitDiffArtifactDTO):
        raise ValueError("Expected a git diff artifact")

    return result


def upsert_pull_request(
    *,
    team_id: int,
    run_id: UUID,
    url: str,
    number: int,
    repository: str,
    head_branch: str,
    base_branch: str,
) -> WizardRunPullRequestArtifactDTO:
    with transaction.atomic():
        WizardRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        existing_metadata = (
            WizardRunArtifact.objects.for_team(team_id)
            .filter(run_id=run_id, type=WizardRunArtifactType.PULL_REQUEST.value)
            .values_list("metadata", flat=True)
            .first()
        )
        artifact, _ = WizardRunArtifact.objects.for_team(team_id).update_or_create(
            run_id=run_id,
            type=WizardRunArtifactType.PULL_REQUEST.value,
            defaults={
                "team_id": team_id,
                "storage_path": None,
                "external_url": url,
                # A retried handoff must not reset a state that a webhook already recorded.
                "metadata": {
                    "state": WizardPullRequestState.OPEN.value,
                    **(existing_metadata or {}),
                    **pull_request_metadata_to_record(number, repository, head_branch, base_branch),
                },
                "size_bytes": None,
                "content_hash": None,
            },
        )

    result = record_to_artifact(artifact)

    if not isinstance(result, WizardRunPullRequestArtifactDTO):
        raise ValueError("Expected a pull request artifact")

    return result


def update_pull_request_state(
    *,
    team_id: int,
    artifact_id: UUID,
    state: WizardPullRequestState,
    updated_at: datetime,
    merged_at: datetime | None,
    closed_at: datetime | None,
) -> bool:
    with transaction.atomic():
        artifact = (
            WizardRunArtifact.objects.for_team(team_id)
            .select_for_update()
            .filter(id=artifact_id, type=WizardRunArtifactType.PULL_REQUEST.value)
            .first()
        )
        if artifact is None:
            return False

        metadata = artifact.metadata or {}
        stored_updated_at = metadata.get("state_updated_at")
        if isinstance(stored_updated_at, str):
            stored = parse_datetime(stored_updated_at)
            # GitHub can deliver out of order, so an older delivery must not overwrite a newer state.
            if stored is not None and stored > updated_at:
                return False

        artifact.metadata = {
            **metadata,
            "state": state.value,
            "state_updated_at": updated_at.isoformat(),
            "merged_at": merged_at.isoformat() if merged_at is not None else None,
            "closed_at": closed_at.isoformat() if closed_at is not None else None,
        }
        artifact.save(update_fields=["metadata"])
        return True


def find_pull_request_owner(team_ids: tuple[int, ...], url: str) -> PullRequestOwner | None:
    stored = (
        WizardRunArtifact.objects.unscoped()
        .filter(team_id__in=team_ids, type=WizardRunArtifactType.PULL_REQUEST.value, external_url=url)
        .values("team_id", "run_id", "id")
        .first()
    )
    if stored is None:
        return None
    return PullRequestOwner(team_id=stored["team_id"], run_id=stored["run_id"], artifact_id=stored["id"])


def find_cloud_run_owners(
    *, team_ids: tuple[int, ...], id_from: UUID, id_to: UUID, repository: str, limit: int
) -> list[PullRequestOwner]:
    runs = (
        WizardRun.objects.unscoped()
        .filter(
            team_id__in=team_ids,
            id__gte=id_from,
            id__lte=id_to,
            environment=WizardRunEnvironment.CLOUD.value,
            workspace_type=WizardWorkspaceType.GIT_REPOSITORY.value,
            workspace__repository__iexact=repository,
        )
        .values("team_id", "id")[:limit]
    )
    return [PullRequestOwner(team_id=run["team_id"], run_id=run["id"], artifact_id=None) for run in runs]


def get_pull_request_url(team_id: int, run_id: UUID) -> str | None:
    return (
        WizardRunArtifact.objects.for_team(team_id)
        .filter(run_id=run_id, type=WizardRunArtifactType.PULL_REQUEST.value)
        .values_list("external_url", flat=True)
        .first()
    )


def list_artifacts(team_id: int, run_id: UUID) -> list[WizardRunArtifactDTO]:
    artifacts = WizardRunArtifact.objects.for_team(team_id).filter(run_id=run_id).order_by("created_at", "id")
    return [record_to_artifact(artifact) for artifact in artifacts]


def get_stored_git_diff_artifact(team_id: int, run_id: UUID, artifact_id: UUID) -> StoredGitDiffArtifact | None:
    stored = (
        WizardRunArtifact.objects.for_team(team_id)
        .filter(id=artifact_id, run_id=run_id, type=WizardRunArtifactType.GIT_DIFF.value)
        .values_list("storage_path", "content_hash", "size_bytes")
        .first()
    )

    if stored is None:
        return None

    storage_path, content_hash, size_bytes = stored

    if not isinstance(storage_path, str) or not isinstance(content_hash, str) or not isinstance(size_bytes, int):
        return None

    return StoredGitDiffArtifact(storage_path=storage_path, content_hash=content_hash, size_bytes=size_bytes)
