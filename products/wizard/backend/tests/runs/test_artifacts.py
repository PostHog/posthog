from hashlib import sha256

import pytest
from unittest.mock import patch

from django.conf import settings

from posthog.models import Team

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreatePullRequestArtifactInput,
    LocalFolderWorkspace,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunArtifactType, WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import WizardRunArtifactTooLargeError, WizardRunNotFoundError
from products.wizard.backend.logic.registry.config import FALLBACK_REGISTRY
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.models import WizardRunArtifact


def _create_run(team_id: int, user_id: int) -> WizardRunDTO:
    return run_store.create_run(
        team_id=team_id,
        created_by_id=user_id,
        environment=WizardRunEnvironment.LOCAL,
        workspace=LocalFolderWorkspace(project_name="example-project"),
        program=FALLBACK_REGISTRY.programs[0],
        status=WizardRunStatus.RUNNING,
    ).run


@pytest.mark.django_db
def test_create_git_diff_artifact_stores_content_by_reference(team, user) -> None:
    run = _create_run(team.id, user.id)
    diff = b"diff --git a/app.py b/app.py\n"

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write") as write:
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, diff)

    assert artifact is not None
    assert artifact.team_id == team.id
    assert artifact.run_id == run.id
    assert artifact.artifact_type == WizardRunArtifactType.GIT_DIFF
    assert artifact.size_bytes == len(diff)
    write.assert_called_once_with(
        f"projects/{team.id}/wizard-runs/{run.id}/artifacts/git-diff-{sha256(diff).hexdigest()}.patch",
        diff,
        extras={"ContentType": "text/x-diff; charset=utf-8"},
        bucket=settings.WIZARD_RUN_ARTIFACTS_S3_BUCKET,
    )
    assert wizard_facade.list_run_artifacts(team.id, run.id) == [artifact]


@pytest.mark.django_db
def test_git_diff_artifact_does_not_download_oversized_content(team, user) -> None:
    run = _create_run(team.id, user.id)

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, b"expected")

    assert artifact is not None
    WizardRunArtifact.objects.for_team(team.id).filter(id=artifact.id).update(size_bytes=2 * 1024 * 1024 + 1)
    with (
        patch("products.wizard.backend.logic.artifacts.service.object_storage.read_bytes") as read_bytes,
        pytest.raises(WizardRunArtifactTooLargeError),
    ):
        wizard_facade.get_git_diff_artifact_content(team.id, run.id, artifact.id)
    read_bytes.assert_not_called()


@pytest.mark.django_db
def test_git_diff_artifact_rejects_changed_stored_content(team, user) -> None:
    run = _create_run(team.id, user.id)

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, b"expected")

    assert artifact is not None
    with (
        patch("products.wizard.backend.logic.artifacts.service.object_storage.read_bytes", return_value=b"changed"),
        pytest.raises(ValueError, match="integrity check"),
    ):
        wizard_facade.get_git_diff_artifact_content(team.id, run.id, artifact.id)


@pytest.mark.django_db
def test_empty_git_diff_creates_no_artifact(team, user) -> None:
    run = _create_run(team.id, user.id)

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write") as write:
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, b"")

    assert artifact is None
    assert wizard_facade.list_run_artifacts(team.id, run.id) == []
    write.assert_not_called()


@pytest.mark.django_db
def test_git_diff_artifact_stores_line_change_counts(team, user) -> None:
    run = _create_run(team.id, user.id)
    diff = (
        b"diff --git a/app.py b/app.py\n"
        b"+++ b/app.py\n"
        b"--- a/app.py\n"
        b"@@ -1,2 +1,3 @@\n"
        b"+added one\n"
        b"+added two\n"
        b"-removed one\n"
        b" kept line\n"
    )

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, diff)

    assert artifact is not None
    assert artifact.additions == 2
    assert artifact.removals == 1

    listed = wizard_facade.list_run_artifacts(team.id, run.id)[0]
    assert isinstance(listed, WizardRunGitDiffArtifactDTO)
    assert listed.additions == 2
    assert listed.removals == 1


@pytest.mark.django_db
def test_git_diff_artifact_without_stored_counts_maps_to_none(team, user) -> None:
    run = _create_run(team.id, user.id)

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, b"diff --git a/app.py b/app.py\n")

    assert artifact is not None
    WizardRunArtifact.objects.for_team(team.id).filter(id=artifact.id).update(metadata=None)

    listed = wizard_facade.list_run_artifacts(team.id, run.id)[0]
    assert isinstance(listed, WizardRunGitDiffArtifactDTO)
    assert listed.additions is None
    assert listed.removals is None


@pytest.mark.django_db
def test_oversized_git_diff_creates_no_artifact(team, user) -> None:
    run = _create_run(team.id, user.id)

    with (
        patch("products.wizard.backend.logic.artifacts.service.MAX_GIT_DIFF_BYTES", 4),
        patch("products.wizard.backend.logic.artifacts.service.object_storage.write") as write,
        patch("products.wizard.backend.logic.artifacts.service.run_observability") as observability,
    ):
        artifact = wizard_facade.create_git_diff_artifact(team.id, run.id, b"12345")

    assert artifact is None
    write.assert_not_called()
    observability.git_diff_omitted.assert_called_once_with(run, 5)


@pytest.mark.django_db
def test_git_diff_artifact_is_idempotent_for_run(team, user) -> None:
    run = _create_run(team.id, user.id)

    with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
        first = wizard_facade.create_git_diff_artifact(team.id, run.id, b"first")
        second = wizard_facade.create_git_diff_artifact(team.id, run.id, b"second")

    assert first is not None
    assert second is not None
    assert second.id == first.id
    assert second.size_bytes == len(b"second")
    assert wizard_facade.list_run_artifacts(team.id, run.id) == [second]


@pytest.mark.django_db
def test_create_git_diff_artifact_is_scoped_to_team(team, user) -> None:
    other_team = Team.objects.create(organization=team.organization, project=team.project, name="Other environment")
    run = _create_run(team.id, user.id)

    with (
        patch("products.wizard.backend.logic.artifacts.service.object_storage.write") as write,
        pytest.raises(WizardRunNotFoundError),
    ):
        wizard_facade.create_git_diff_artifact(other_team.id, run.id, b"diff")

    write.assert_not_called()


@pytest.mark.django_db
def test_create_pull_request_artifact_persists_pull_request_identity(team, user) -> None:
    run = _create_run(team.id, user.id)
    params = CreatePullRequestArtifactInput(
        team_id=team.id,
        run_id=run.id,
        url="https://github.com/posthog/posthog/pull/123",
        number=123,
        repository="posthog/posthog",
        head_branch="posthog/wizard-123",
        base_branch="master",
    )

    artifact = wizard_facade.create_pull_request_artifact(params)

    assert isinstance(artifact, WizardRunPullRequestArtifactDTO)
    assert artifact.artifact_type == WizardRunArtifactType.PULL_REQUEST
    assert artifact.url == params.url
    assert artifact.number == params.number
    assert artifact.repository == params.repository
    assert artifact.head_branch == params.head_branch
    assert artifact.base_branch == params.base_branch
    assert wizard_facade.list_run_artifacts(team.id, run.id) == [artifact]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("artifact_type", "external_url", "metadata", "size_bytes", "content_hash"),
    [
        (WizardRunArtifactType.GIT_DIFF, None, None, None, None),
        (WizardRunArtifactType.PULL_REQUEST, None, {}, None, None),
    ],
)
def test_list_run_artifacts_rejects_incomplete_persisted_metadata(
    team,
    user,
    artifact_type: WizardRunArtifactType,
    external_url: str | None,
    metadata: dict[str, object] | None,
    size_bytes: int | None,
    content_hash: str | None,
) -> None:
    run = _create_run(team.id, user.id)
    WizardRunArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run_id=run.id,
        type=artifact_type.value,
        external_url=external_url,
        metadata=metadata,
        size_bytes=size_bytes,
        content_hash=content_hash,
    )

    with pytest.raises(ValueError):
        wizard_facade.list_run_artifacts(team.id, run.id)
