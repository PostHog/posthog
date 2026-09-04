import pytest
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.db.models import NOT_PROVIDED

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.config import DEFAULT_WIZARD_VERSION
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    WizardProgram,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import (
    InvalidRepositoryError,
    InvalidWorkspaceEnvironmentError,
    MissingGitHubIntegrationError,
    RepositoryNotAccessibleError,
    WizardProgramEnvironmentNotSupportedError,
)
from products.wizard.backend.models import WizardRun
from products.wizard.backend.temporal.contracts import WizardRunActivityInput
from products.wizard.backend.temporal.errors import WizardTemporalError

PROGRAM_DEFINITION = {
    "id": "web-analytics-audit",
    "name": "Web analytics audit",
    "description": "Audit a project's web analytics setup",
    "wizard_version": "2.60.0",
    "command": ["audit", "web-analytics"],
    "tags": ["audit", "web-analytics"],
    "required_programs": ["posthog-integration"],
    "supported_environments": ["local"],
}
PROGRAM_PAYLOAD = {"version": 1, "programs": [PROGRAM_DEFINITION]}


@pytest.mark.django_db
def test_create_run_persists_resolved_program(team, user) -> None:
    with patch("posthoganalytics.get_feature_flag_payload", return_value=PROGRAM_PAYLOAD):
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="example-project"),
                program_id="web-analytics-audit",
            )
        )

    assert run.program == WizardProgram(
        id="web-analytics-audit",
        name="Web analytics audit",
        description="Audit a project's web analytics setup",
        wizard_version=DEFAULT_WIZARD_VERSION,
        command=("audit", "web-analytics"),
        tags=("audit", "web-analytics"),
        required_programs=("posthog-integration",),
        supported_environments=(WizardRunEnvironment.LOCAL,),
    )
    assert WizardRun.objects.for_team(team.id).get(id=run.id).program == {
        **PROGRAM_DEFINITION,
        "wizard_version": DEFAULT_WIZARD_VERSION,
    }


@pytest.mark.django_db
def test_create_run_rejects_unsupported_program_environment(team, user) -> None:
    with (
        patch("posthoganalytics.get_feature_flag_payload", return_value=PROGRAM_PAYLOAD),
        pytest.raises(WizardProgramEnvironmentNotSupportedError),
    ):
        wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="unsupported-program-environment",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
                program_id="web-analytics-audit",
            )
        )

    assert not WizardRun.objects.for_team(team.id).exists()


@pytest.mark.django_db
def test_run_program_has_no_default_and_cannot_be_null(team, user) -> None:
    program_field = WizardRun._meta.get_field("program")

    assert program_field.default is NOT_PROVIDED
    assert program_field.null is False
    with pytest.raises(IntegrityError), transaction.atomic():
        WizardRun.objects.create(
            team=team,
            created_by=user,
            environment=WizardRunEnvironment.LOCAL.value,
            workspace_type="local_folder",
            workspace={"project_name": "example-project"},
            status=WizardRunStatus.RUNNING.value,
        )


@pytest.mark.django_db
def test_local_run_starts_running(team, user) -> None:
    run = wizard_facade.create_run(
        CreateWizardRunInput(
            team_id=team.id,
            created_by_id=user.id,
            program_id="posthog-integration",
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example-project"),
        )
    )

    assert run.team_id == team.id
    assert run.created_by_id == user.id
    assert run.environment == WizardRunEnvironment.LOCAL
    assert run.workspace == LocalFolderWorkspace(project_name="example-project")
    assert run.status == WizardRunStatus.RUNNING
    assert run.error_code is None


@pytest.mark.django_db
def test_create_run_rejects_unsupported_environment_workspace(team, user) -> None:
    with pytest.raises(InvalidWorkspaceEnvironmentError):
        wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )

    assert not WizardRun.objects.for_team(team.id).exists()


@pytest.mark.django_db
def test_cloud_run_starts_created(team, user) -> None:
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
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="cloud-run-created",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )

    assert run.status == WizardRunStatus.CREATED
    assert run.workspace == GitRepositoryWorkspace(repository="posthog/posthog")


@pytest.mark.django_db(transaction=True)
def test_cloud_run_dispatches_after_persistence(team, user) -> None:
    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch(
            "products.wizard.backend.logic.runs.lifecycle.dispatch_created_cloud_wizard_run_to_temporal_worker"
        ) as dispatch_wizard_run,
    ):
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="cloud-run-dispatch",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )

    dispatch_wizard_run.assert_called_once_with(team.id, run.id)
    assert run.status == WizardRunStatus.CREATED


@pytest.mark.django_db(transaction=True)
def test_cloud_run_cancellation_during_dispatch_reaches_temporal(team, user) -> None:
    def cancel_during_dispatch(input: WizardRunActivityInput) -> None:
        wizard_facade.cancel_run(input.team_id, input.run_id)

    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch(
            "products.wizard.backend.logic.runs.dispatch.temporal_client.start_wizard_run_workflow",
            side_effect=cancel_during_dispatch,
        ),
        patch(
            "products.wizard.backend.logic.runs.cancellation.temporal_client.cancel_wizard_run_workflow"
        ) as cancel_workflow,
    ):
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="cloud-run-cancel-during-dispatch",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )

    record = WizardRun.objects.for_team(team.id).get(id=run.id)
    cancel_workflow.assert_called_once_with(run.id)
    assert record.status == WizardRunStatus.CANCELLED.value
    assert record.cancellation_requested_at is not None
    assert record.cancellation_dispatched_at is not None


@pytest.mark.django_db(transaction=True)
def test_cloud_run_survives_temporal_dispatch_failure(team, user) -> None:
    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch(
            "products.wizard.backend.logic.runs.dispatch.temporal_client.start_wizard_run_workflow",
            side_effect=WizardTemporalError,
        ),
    ):
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="cloud-run-dispatch-failure",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )

    record = WizardRun.objects.for_team(team.id).get(id=run.id)
    assert run.status == WizardRunStatus.CREATED
    assert run.error_code is None
    assert record.dispatch_status == "pending"
    assert record.dispatch_attempts == 1
    assert record.dispatch_error == "Temporal dispatch failed."


@pytest.mark.django_db(transaction=True)
def test_cloud_run_rollback_prevents_dispatch(team, user) -> None:
    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch(
            "products.wizard.backend.logic.runs.lifecycle.dispatch_created_cloud_wizard_run_to_temporal_worker"
        ) as dispatch,
        transaction.atomic(),
    ):
        wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="cloud-run-rollback",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )
        transaction.set_rollback(True)

    dispatch.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_local_run_does_not_dispatch(team, user) -> None:
    with patch(
        "products.wizard.backend.logic.runs.lifecycle.dispatch_created_cloud_wizard_run_to_temporal_worker"
    ) as dispatch:
        wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="example-project"),
            )
        )

    dispatch.assert_not_called()


@pytest.mark.django_db
def test_cloud_run_requires_github_integration(team, user) -> None:
    with patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=None,
    ):
        with pytest.raises(MissingGitHubIntegrationError):
            wizard_facade.create_run(
                CreateWizardRunInput(
                    team_id=team.id,
                    created_by_id=user.id,
                    program_id="posthog-integration",
                    environment=WizardRunEnvironment.CLOUD,
                    idempotency_key="missing-integration",
                    workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
                )
            )

    assert not WizardRun.objects.for_team(team.id).exists()


@pytest.mark.django_db
def test_cloud_run_rejects_inaccessible_repository(team, user) -> None:
    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=False,
        ),
    ):
        with pytest.raises(RepositoryNotAccessibleError):
            wizard_facade.create_run(
                CreateWizardRunInput(
                    team_id=team.id,
                    created_by_id=user.id,
                    program_id="posthog-integration",
                    environment=WizardRunEnvironment.CLOUD,
                    idempotency_key="inaccessible-repository",
                    workspace=GitRepositoryWorkspace(repository="private/example"),
                )
            )


@pytest.mark.parametrize("repository", ("posthog", "/posthog", "posthog/", "posthog/posthog/extra"))
@pytest.mark.django_db
def test_cloud_run_rejects_invalid_repository_before_github_lookup(team, user, repository: str) -> None:
    with patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id"
    ) as resolve:
        with pytest.raises(InvalidRepositoryError):
            wizard_facade.create_run(
                CreateWizardRunInput(
                    team_id=team.id,
                    created_by_id=user.id,
                    program_id="posthog-integration",
                    environment=WizardRunEnvironment.CLOUD,
                    idempotency_key=f"repository-{repository}",
                    workspace=GitRepositoryWorkspace(repository=repository),
                )
            )

    resolve.assert_not_called()
    assert not WizardRun.objects.for_team(team.id).exists()
