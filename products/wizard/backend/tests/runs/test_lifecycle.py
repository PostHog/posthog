from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from posthog.models import Team

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    UpdateWizardRunTaskInput,
    WizardRunDTO,
)
from products.wizard.backend.facade.enums import (
    WizardRunEnvironment,
    WizardRunErrorCode,
    WizardRunStatus,
    WizardTaskStatus,
)
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, WizardRunNotFoundError
from products.wizard.backend.logic.runs.lifecycle import _compute_task_list_derived_fields


@pytest.mark.parametrize("status", tuple(WizardTaskStatus))
def test_task_snapshot_preserves_first_observed_timestamps(status: WizardTaskStatus) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tasks = (UpdateWizardRunTaskInput(title="Install SDK", status=status),)
    initial = _compute_task_list_derived_fields(tasks, (), now)
    repeated = _compute_task_list_derived_fields(tasks, initial, now + timedelta(minutes=1))
    assert repeated == initial
    assert initial[0].created_at == now
    assert initial[0].started_at == (now if status == WizardTaskStatus.RUNNING else None)
    assert initial[0].completed_at == (now if status == WizardTaskStatus.COMPLETED else None)
    assert initial[0].failed_at == (now if status == WizardTaskStatus.FAILED else None)


@pytest.mark.django_db
def test_task_snapshots_round_trip_and_replace_in_order(team, user) -> None:
    run = _create_local_run(team.id, user.id)
    initial = wizard_facade.update_run_task_list(
        team.id,
        run.id,
        (
            UpdateWizardRunTaskInput(title="Install SDK", status=WizardTaskStatus.RUNNING),
            UpdateWizardRunTaskInput(title="Configure events", status=WizardTaskStatus.CREATED),
            UpdateWizardRunTaskInput(title="Remove me", status=WizardTaskStatus.CREATED),
        ),
    )
    updated = wizard_facade.update_run_task_list(
        team.id,
        run.id,
        (
            UpdateWizardRunTaskInput(title="Configure events", status=WizardTaskStatus.RUNNING),
            UpdateWizardRunTaskInput(title="Install SDK", status=WizardTaskStatus.COMPLETED),
            UpdateWizardRunTaskInput(title="Verify capture", status=WizardTaskStatus.FAILED),
        ),
    )
    assert wizard_facade.get_run(team.id, run.id).tasks == updated
    assert [task.title for task in updated] == ["Configure events", "Install SDK", "Verify capture"]
    assert updated[0].created_at == initial[1].created_at
    assert updated[0].started_at is not None
    assert updated[1].started_at == initial[0].started_at
    assert updated[1].completed_at is not None
    assert updated[2].failed_at is not None
    assert updated[2].started_at is None
    wizard_facade.update_run_task_list(team.id, run.id, ())
    assert wizard_facade.get_run(team.id, run.id).tasks == ()


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
