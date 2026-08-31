import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import CreateWizardRunInput, GitRepositoryWorkspace
from products.wizard.backend.facade.enums import WizardRunEnvironment
from products.wizard.backend.logic.workers.service import WizardExecutionRequest
from products.wizard.backend.temporal.activities.execution import execute_wizard
from products.wizard.backend.temporal.contracts import PreparedGitRepositoryWorkspace


async def _run_execute_wizard(input: PreparedGitRepositoryWorkspace) -> None:
    await ActivityEnvironment().run(execute_wizard, input)


@pytest.mark.django_db(transaction=True)
def test_execute_wizard_uses_persisted_program_snapshot(team, user) -> None:
    registry_payload = {
        "version": 1,
        "programs": [
            {
                "id": "web-analytics-audit",
                "name": "Web analytics audit",
                "description": "Audit a project's web analytics setup",
                "wizard_version": "2.60.0",
                "command": ["audit", "web-analytics"],
                "tags": ["audit", "web-analytics"],
                "required_programs": ["posthog-integration"],
                "supported_environments": ["cloud"],
            }
        ],
    }
    with (
        patch("posthoganalytics.get_feature_flag_payload", return_value=registry_payload),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch("products.wizard.backend.logic.runs.lifecycle.dispatch_created_cloud_wizard_run_to_temporal_worker"),
    ):
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="test-cloud-execution",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
                program_id="web-analytics-audit",
            )
        )

    workspace = PreparedGitRepositoryWorkspace(
        team_id=team.id,
        run_id=run.id,
        sandbox_id="worker-id",
        repository="posthog/posthog",
        root_path="/tmp/workspace/repos/posthog/posthog",
        github_integration_id=456,
    )
    with (
        patch("posthoganalytics.get_feature_flag_payload", side_effect=AssertionError("registry was re-evaluated")),
        patch("products.wizard.backend.temporal.activities.execution.cloud_worker.execute_wizard") as execute,
    ):
        async_to_sync(_run_execute_wizard)(workspace)

    execute.assert_called_once_with(
        WizardExecutionRequest(
            sandbox_id="worker-id",
            workspace_path="/tmp/workspace/repos/posthog/posthog",
            team_id=team.id,
            wizard_version="2.60.0",
            program_command=("audit", "web-analytics"),
        )
    )
