import pytest
from unittest.mock import patch

from posthog.models import Team

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    WizardRunDTO,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunErrorCode, WizardRunStatus
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, WizardRunNotFoundError


def _create_local_run(team_id: int, user_id: int) -> WizardRunDTO:
    return wizard_facade.create_run(
        CreateWizardRunInput(
            team_id=team_id,
            created_by_id=user_id,
            program_id="posthog-integration",
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example-project"),
        )
    )


def _create_cloud_run(team_id: int, user_id: int) -> WizardRunDTO:
    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
    ):
        return wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team_id,
                created_by_id=user_id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="test-lifecycle",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )


@pytest.mark.django_db
def test_get_run_is_scoped_to_team(team, user) -> None:
    other_team = Team.objects.create(organization=team.organization, project=team.project, name="Other environment")
    created = _create_local_run(team.id, user.id)

    assert wizard_facade.get_run(team.id, created.id) == created

    with pytest.raises(WizardRunNotFoundError):
        wizard_facade.get_run(other_team.id, created.id)


@pytest.mark.django_db
def test_start_run_persists_running_status(team, user) -> None:
    created = _create_cloud_run(team.id, user.id)

    started = wizard_facade.update_run_status(team.id, created.id, WizardRunStatus.RUNNING)

    assert started.status == WizardRunStatus.RUNNING
    assert started.started_at is not None
    assert started.finished_at is None
    assert wizard_facade.get_run(team.id, created.id) == started


@pytest.mark.parametrize("expected_status", (WizardRunStatus.COMPLETED, WizardRunStatus.CANCELLED))
@pytest.mark.django_db
def test_running_run_persists_terminal_status(team, user, expected_status: WizardRunStatus) -> None:
    created = _create_local_run(team.id, user.id)

    if expected_status == WizardRunStatus.CANCELLED:
        transitioned = wizard_facade.cancel_run(team.id, created.id)
    else:
        transitioned = wizard_facade.update_run_status(team.id, created.id, expected_status)

    assert transitioned.status == expected_status
    assert transitioned.finished_at is not None
    assert transitioned.stage is None
    assert wizard_facade.get_run(team.id, created.id) == transitioned


@pytest.mark.django_db
def test_fail_run_persists_error_code(team, user) -> None:
    created = _create_local_run(team.id, user.id)

    failed = wizard_facade.update_run_status(
        team.id,
        created.id,
        WizardRunStatus.FAILED,
        error_code=WizardRunErrorCode.TIMEOUT,
    )

    assert failed.status == WizardRunStatus.FAILED
    assert failed.error_code == WizardRunErrorCode.TIMEOUT
    assert failed.error_message == "The Wizard run timed out."
    assert failed.finished_at is not None
    assert wizard_facade.get_run(team.id, created.id) == failed


@pytest.mark.django_db
def test_fail_run_persists_wizard_error_code(team, user) -> None:
    created = _create_local_run(team.id, user.id)

    failed = wizard_facade.update_run_status(
        team.id,
        created.id,
        WizardRunStatus.FAILED,
        error_code="PHW_DETECT_NO_POSTHOG_SDK",
    )

    assert failed.error_code == "PHW_DETECT_NO_POSTHOG_SDK"
    assert failed.error_message == "The Wizard could not complete the selected program."


@pytest.mark.django_db
def test_invalid_persisted_transition_leaves_run_unchanged(team, user) -> None:
    created = _create_local_run(team.id, user.id)
    completed = wizard_facade.update_run_status(team.id, created.id, WizardRunStatus.COMPLETED)

    with pytest.raises(IllegalStatusTransitionError):
        wizard_facade.cancel_run(team.id, created.id)

    assert wizard_facade.get_run(team.id, created.id) == completed


@pytest.mark.django_db
def test_transition_run_is_scoped_to_team(team, user) -> None:
    other_team = Team.objects.create(organization=team.organization, project=team.project, name="Other environment")
    created = _create_cloud_run(team.id, user.id)

    with pytest.raises(WizardRunNotFoundError):
        wizard_facade.update_run_status(other_team.id, created.id, WizardRunStatus.RUNNING)

    assert wizard_facade.get_run(team.id, created.id) == created
