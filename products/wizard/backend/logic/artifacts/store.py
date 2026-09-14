from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunArtifactType
from products.wizard.backend.logic.artifacts.mappers import pull_request_metadata_to_record, record_to_artifact
from products.wizard.backend.models import WizardRun, WizardRunArtifact


@frozen
class StoredGitDiffArtifact:
    storage_path: str
    content_hash: str
    size_bytes: int


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
        artifact, _ = WizardRunArtifact.objects.for_team(team_id).update_or_create(
            run_id=run_id,
            type=WizardRunArtifactType.PULL_REQUEST.value,
            defaults={
                "team_id": team_id,
                "storage_path": None,
                "external_url": url,
                "metadata": pull_request_metadata_to_record(number, repository, head_branch, base_branch),
                "size_bytes": None,
                "content_hash": None,
            },
        )

    result = record_to_artifact(artifact)

    if not isinstance(result, WizardRunPullRequestArtifactDTO):
        raise ValueError("Expected a pull request artifact")

    return result


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
