from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunArtifactType
from products.wizard.backend.models import WizardRunArtifact


def artifact_from_record(artifact: WizardRunArtifact) -> WizardRunArtifactDTO:
    if WizardRunArtifactType(artifact.type) == WizardRunArtifactType.GIT_DIFF:
        if artifact.size_bytes is None or artifact.content_hash is None:
            raise ValueError("Git diff artifact is missing stored content metadata.")
        metadata = artifact.metadata or {}
        additions = metadata.get("additions")
        removals = metadata.get("removals")
        return WizardRunGitDiffArtifactDTO(
            id=artifact.id,
            team_id=artifact.team_id,
            run_id=artifact.run_id,
            artifact_type=WizardRunArtifactType.GIT_DIFF,
            size_bytes=artifact.size_bytes,
            content_hash=artifact.content_hash,
            additions=additions if isinstance(additions, int) else None,
            removals=removals if isinstance(removals, int) else None,
            created_at=artifact.created_at,
        )

    metadata = artifact.metadata or {}
    number = metadata.get("number")
    repository = metadata.get("repository")
    head_branch = metadata.get("head_branch")
    base_branch = metadata.get("base_branch")
    if (
        artifact.external_url is None
        or not isinstance(number, int)
        or not isinstance(repository, str)
        or not isinstance(head_branch, str)
        or not isinstance(base_branch, str)
    ):
        raise ValueError("Pull request artifact is missing repository metadata.")
    return WizardRunPullRequestArtifactDTO(
        id=artifact.id,
        team_id=artifact.team_id,
        run_id=artifact.run_id,
        artifact_type=WizardRunArtifactType.PULL_REQUEST,
        url=artifact.external_url,
        number=number,
        repository=repository,
        head_branch=head_branch,
        base_branch=base_branch,
        created_at=artifact.created_at,
    )


def pull_request_metadata_to_record(
    number: int, repository: str, head_branch: str, base_branch: str
) -> dict[str, object]:
    return {
        "number": number,
        "repository": repository,
        "head_branch": head_branch,
        "base_branch": base_branch,
    }
