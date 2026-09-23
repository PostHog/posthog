import logging
from hashlib import sha256
from uuid import UUID

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.wizard.backend.facade.config import WIZARD_GIT_DIFF_CONTENT_TYPE
from products.wizard.backend.facade.contracts import (
    CreatePullRequestArtifactInput,
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.errors import WizardRunArtifactNotFoundError, WizardRunArtifactTooLargeError
from products.wizard.backend.logic.artifacts import store
from products.wizard.backend.logic.artifacts.config import MAX_GIT_DIFF_BYTES, MAX_GIT_DIFF_DOWNLOAD_BYTES
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.observability.service import wizard_observability as run_observability

logger = logging.getLogger(__name__)


@frozen
class _DiffLineCounts:
    additions: int
    removals: int


def create_git_diff_artifact(team_id: int, run_id: UUID, content: bytes) -> WizardRunGitDiffArtifactDTO | None:
    if not content:
        return None

    run = run_store.get_run(team_id, run_id)

    if len(content) > MAX_GIT_DIFF_BYTES:
        run_observability.git_diff_omitted(run, len(content))
        return None

    content_hash = sha256(content).hexdigest()
    storage_path = _git_diff_storage_path(team_id, run_id, content_hash)
    line_counts = _diff_line_counts(content)

    object_storage.write(
        storage_path,
        content,
        extras={"ContentType": WIZARD_GIT_DIFF_CONTENT_TYPE},
        bucket=settings.WIZARD_RUN_ARTIFACTS_S3_BUCKET,
    )

    artifact = store.upsert_git_diff(
        team_id=team_id,
        run_id=run.id,
        storage_path=storage_path,
        size_bytes=len(content),
        content_hash=content_hash,
        additions=line_counts.additions,
        removals=line_counts.removals,
    )

    run_observability.artifact_created(run, artifact)
    return artifact


def create_pull_request_artifact(params: CreatePullRequestArtifactInput) -> WizardRunPullRequestArtifactDTO:
    run = run_store.get_run(params.team_id, params.run_id)

    artifact = store.upsert_pull_request(
        team_id=params.team_id,
        run_id=run.id,
        url=params.url,
        number=params.number,
        repository=params.repository,
        head_branch=params.head_branch,
        base_branch=params.base_branch,
    )

    run_observability.pull_request_created(run, artifact)
    return artifact


def list_run_artifacts(team_id: int, run_id: UUID) -> list[WizardRunArtifactDTO]:
    run = run_store.get_run(team_id, run_id)

    return store.list_artifacts(team_id, run.id)


def get_git_diff_artifact_content(team_id: int, run_id: UUID, artifact_id: UUID) -> bytes:
    run = run_store.get_run(team_id, run_id)
    stored_artifact = store.get_stored_git_diff_artifact(team_id, run.id, artifact_id)

    if stored_artifact is None:
        raise WizardRunArtifactNotFoundError

    if stored_artifact.size_bytes > MAX_GIT_DIFF_DOWNLOAD_BYTES:
        raise WizardRunArtifactTooLargeError

    content = object_storage.read_bytes(
        stored_artifact.storage_path,
        bucket=settings.WIZARD_RUN_ARTIFACTS_S3_BUCKET,
        missing_ok=True,
    )

    if content is None:
        raise WizardRunArtifactNotFoundError

    content_hash = sha256(content).hexdigest()
    if content_hash != stored_artifact.content_hash:
        logger.error(
            "wizard_git_diff_integrity_check_failed",
            extra={"team_id": team_id, "run_id": str(run_id), "artifact_id": str(artifact_id)},
        )
        raise ValueError("Stored Wizard diff failed its integrity check")

    return content


def _diff_line_counts(content: bytes) -> _DiffLineCounts:
    additions = 0
    removals = 0
    for line in content.split(b"\n"):
        if line.startswith(b"+++") or line.startswith(b"---"):
            continue
        if line.startswith(b"+"):
            additions += 1
        elif line.startswith(b"-"):
            removals += 1
    return _DiffLineCounts(additions=additions, removals=removals)


def _git_diff_storage_path(team_id: int, run_id: UUID, content_hash: str) -> str:
    return f"projects/{team_id}/wizard-runs/{run_id}/artifacts/git-diff-{content_hash}.patch"
