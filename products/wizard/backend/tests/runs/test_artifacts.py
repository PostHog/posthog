from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
from unittest.mock import patch

from django.conf import settings

from posthog.models import Team

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreatePullRequestArtifactInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    MatchWizardPullRequestInput,
    RecordWizardPullRequestStateInput,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import (
    WizardPullRequestState,
    WizardRunArtifactType,
    WizardRunEnvironment,
    WizardRunStatus,
)
from products.wizard.backend.facade.errors import WizardRunArtifactTooLargeError, WizardRunNotFoundError
from products.wizard.backend.logic.registry.config import FALLBACK_REGISTRY
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.models import WizardRun, WizardRunArtifact


def _create_run(team_id: int, user_id: int) -> WizardRunDTO:
    return run_store.create_run(
        team_id=team_id,
        created_by_id=user_id,
        environment=WizardRunEnvironment.LOCAL,
        workspace=LocalFolderWorkspace(project_name="example-project"),
        program=FALLBACK_REGISTRY.programs[0],
        status=WizardRunStatus.RUNNING,
    ).run


_REPOSITORY = "acme/widgets"
_PULL_REQUEST_URL = "https://github.com/acme/widgets/pull/7"


def _create_cloud_run(team_id: int, user_id: int) -> WizardRunDTO:
    return run_store.create_run(
        team_id=team_id,
        created_by_id=user_id,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository=_REPOSITORY),
        program=FALLBACK_REGISTRY.programs[0],
        status=WizardRunStatus.RUNNING,
    ).run


def _create_pull_request_artifact(team_id: int, run_id: UUID) -> WizardRunPullRequestArtifactDTO:
    return wizard_facade.create_pull_request_artifact(
        CreatePullRequestArtifactInput(
            team_id=team_id,
            run_id=run_id,
            url=_PULL_REQUEST_URL,
            number=7,
            repository=_REPOSITORY,
            head_branch=f"posthog/wizard-{run_id.hex[:12]}",
            base_branch="main",
        )
    )


def _match_input(team_id: int, run_id: UUID, **overrides: Any) -> MatchWizardPullRequestInput:
    base = MatchWizardPullRequestInput(
        team_ids=(team_id,),
        url=_PULL_REQUEST_URL,
        repository=_REPOSITORY,
        head_branch=f"posthog/wizard-{run_id.hex[:12]}",
        head_repository=_REPOSITORY,
        opened=True,
    )
    return replace(base, **overrides)


@pytest.mark.django_db
@pytest.mark.parametrize("artifact_stored", [True, False])
def test_match_pull_request_finds_the_run_that_opened_it(team, user, artifact_stored: bool) -> None:
    run = _create_cloud_run(team.id, user.id)
    artifact = _create_pull_request_artifact(team.id, run.id) if artifact_stored else None

    match = wizard_facade.match_pull_request(_match_input(team.id, run.id, opened=not artifact_stored))

    assert match is not None
    assert match.team_id == team.id
    assert match.run_id == run.id
    assert match.artifact_id == (artifact.id if artifact else None)
    assert match.created_by_distinct_id == user.distinct_id
    assert match.program_id == run.program.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"head_branch": "posthog/wizard-000000000000"}, id="branch_names_no_run"),
        pytest.param({"opened": False}, id="not_opened_and_no_artifact"),
        pytest.param({"head_repository": "attacker/widgets"}, id="fork"),
        pytest.param({"head_repository": None}, id="unknown_head_repository"),
        pytest.param({"head_branch": "posthog/wizard-my-own-branch"}, id="suffix_is_not_a_run_id"),
        pytest.param({"repository": "acme/other", "head_repository": "acme/other"}, id="other_repository"),
        pytest.param({"team_ids": ()}, id="no_team"),
    ],
)
def test_match_pull_request_rejects_unproven_branch(team, user, overrides: dict[str, object]) -> None:
    run = _create_cloud_run(team.id, user.id)

    assert wizard_facade.match_pull_request(_match_input(team.id, run.id, **overrides)) is None


@pytest.mark.django_db
def test_match_pull_request_ignores_artifact_of_another_team(team, user) -> None:
    other_team = Team.objects.create(organization=team.organization, project=team.project, name="Other environment")
    run = _create_cloud_run(team.id, user.id)
    _create_pull_request_artifact(team.id, run.id)

    assert wizard_facade.match_pull_request(_match_input(other_team.id, run.id, opened=False)) is None


@pytest.mark.django_db
def test_match_pull_request_rejects_runs_sharing_a_branch(team, user) -> None:
    run = _create_cloud_run(team.id, user.id)
    sibling = _create_cloud_run(team.id, user.id)
    WizardRun.objects.for_team(team.id).filter(id=sibling.id).update(id=UUID(run.id.hex[:12] + sibling.id.hex[12:]))

    assert wizard_facade.match_pull_request(_match_input(team.id, run.id)) is None


def _record_state(
    team_id: int, artifact_id: UUID, state: WizardPullRequestState, updated_at: datetime, *, closed: bool
) -> None:
    wizard_facade.record_pull_request_state(
        RecordWizardPullRequestStateInput(
            team_id=team_id,
            artifact_id=artifact_id,
            state=state,
            updated_at=updated_at,
            merged_at=updated_at if state == WizardPullRequestState.MERGED else None,
            closed_at=updated_at if closed else None,
        )
    )


@pytest.mark.django_db
@pytest.mark.parametrize("state", [WizardPullRequestState.MERGED, WizardPullRequestState.CLOSED])
def test_record_pull_request_state_keeps_the_newest_delivery(team, user, state: WizardPullRequestState) -> None:
    run = _create_cloud_run(team.id, user.id)
    artifact = _create_pull_request_artifact(team.id, run.id)
    closed_at = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    _record_state(team.id, artifact.id, state, closed_at, closed=True)
    _record_state(
        team.id, artifact.id, WizardPullRequestState.DRAFT, datetime(2026, 11, 10, 11, 0, tzinfo=UTC), closed=False
    )
    # A retried handoff rewrites the artifact identity and must keep the recorded state.
    _create_pull_request_artifact(team.id, run.id)

    [stored] = wizard_facade.list_run_artifacts(team.id, run.id)
    assert isinstance(stored, WizardRunPullRequestArtifactDTO)
    assert stored.state == state
    assert stored.closed_at == closed_at
    assert stored.merged_at == (closed_at if state == WizardPullRequestState.MERGED else None)


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
