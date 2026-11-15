from datetime import UTC, datetime
from uuid import uuid4

import pytest

from products.wizard.backend.facade.contracts import GitRepositoryWorkspace, WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStage, WizardRunStatus
from products.wizard.backend.logic.installs.next_step import next_step
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM


def _run(status: WizardRunStatus, stage: WizardRunStage | None = None, error_code: str | None = None) -> WizardRunDTO:
    return WizardRunDTO(
        id=uuid4(),
        team_id=1,
        created_by_id=1,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
        program=POSTHOG_INTEGRATION_PROGRAM,
        status=status,
        error_code=error_code,
        error_message=None,
        stage=stage,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=None,
        started_at=None,
        finished_at=None,
        deadline_at=None,
    )


@pytest.mark.parametrize(
    ("run", "pull_request_url", "expected_start"),
    [
        (_run(WizardRunStatus.CREATED), None, "The setup agent is queued."),
        (_run(WizardRunStatus.RUNNING, WizardRunStage.PROVISIONING), None, "The setup agent is starting"),
        (_run(WizardRunStatus.RUNNING, WizardRunStage.EXECUTING_WIZARD), None, "The setup agent is adding PostHog"),
        (_run(WizardRunStatus.COMPLETED), "https://github.com/posthog/posthog/pull/1", "The setup agent opened"),
        (_run(WizardRunStatus.COMPLETED), None, "The setup agent finished without changing any files."),
        (_run(WizardRunStatus.CANCELLED), None, "This run was canceled."),
        (_run(WizardRunStatus.FAILED, error_code="repository_access_failed"), None, "PostHog could not access"),
        (
            _run(WizardRunStatus.FAILED, error_code="workspace_preparation_failed"),
            None,
            "The setup agent could not clone",
        ),
        (_run(WizardRunStatus.FAILED, error_code="timeout"), None, "The run took too long"),
        (
            _run(WizardRunStatus.FAILED, error_code="PHW_DETECT_NO_POSTHOG_SDK"),
            None,
            "The setup agent could not finish.",
        ),
    ],
)
def test_next_step_follows_the_run(run: WizardRunDTO, pull_request_url: str | None, expected_start: str) -> None:
    step = next_step(run, pull_request_url)

    assert step.startswith(expected_start)
    if run.status in (WizardRunStatus.CREATED, WizardRunStatus.RUNNING):
        assert step.endswith("Check the status again in about 30 seconds.")
