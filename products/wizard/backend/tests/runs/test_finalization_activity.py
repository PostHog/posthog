import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import CreateWizardRunInput, GitRepositoryWorkspace, LocalFolderWorkspace
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunErrorCode, WizardRunStatus
from products.wizard.backend.temporal.activities.lifecycle import finalize_run
from products.wizard.backend.temporal.contracts import WizardRunFinalizationActivityInput


async def _run_activity(input: WizardRunFinalizationActivityInput) -> None:
    await ActivityEnvironment().run(finalize_run, input)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        (WizardRunStatus.FAILED, WizardRunErrorCode.TIMEOUT),
        (WizardRunStatus.FAILED, WizardRunErrorCode.EXECUTION_FAILED),
        (WizardRunStatus.FAILED, "PHW_DETECT_NO_POSTHOG_SDK"),
        (WizardRunStatus.CANCELLED, None),
    ),
)
def test_finalize_run_is_retry_safe(team, user, status: WizardRunStatus, error_code: str | None) -> None:
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
                idempotency_key="test-finalization",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
            )
        )
    wizard_facade.update_run_status(team.id, run.id, WizardRunStatus.RUNNING)
    input = WizardRunFinalizationActivityInput(
        team_id=team.id,
        run_id=run.id,
        status=status,
        error_code=error_code,
    )

    async_to_sync(_run_activity)(input)
    async_to_sync(_run_activity)(input)

    persisted = wizard_facade.get_run(team.id, run.id)
    assert persisted.status == status
    assert persisted.error_code == error_code


@pytest.mark.django_db(transaction=True)
def test_finalize_run_rejects_local_run(team, user) -> None:
    run = wizard_facade.create_run(
        CreateWizardRunInput(
            team_id=team.id,
            created_by_id=user.id,
            program_id="posthog-integration",
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example-project"),
        )
    )
    input = WizardRunFinalizationActivityInput(
        team_id=team.id,
        run_id=run.id,
        status=WizardRunStatus.CANCELLED,
    )

    with pytest.raises(ValueError, match="cloud Wizard Run"):
        async_to_sync(_run_activity)(input)
