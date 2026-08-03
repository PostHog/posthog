import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.logic.services.sandbox import ExecutionResult, Sandbox
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CloneRepositoryInSandboxInput,
    _sandbox_image_kind,
    clone_repository_in_sandbox,
)


@pytest.mark.parametrize(
    "image_source, custom_image_name, expected",
    [
        ("custom_image", "posthog-dev-stack", "dev_stack"),
        ("custom_image", "team-image", "custom"),
        ("resume_snapshot", "posthog-dev-stack", "resume_snapshot"),
        ("repository_snapshot", None, "repository_snapshot"),
        ("base_image", None, "base"),
    ],
)
def test_sandbox_image_kind(image_source: str, custom_image_name: str | None, expected: str) -> None:
    assert _sandbox_image_kind(image_source, custom_image_name) == expected


@pytest.mark.parametrize(
    "state, expected_branch",
    [
        ({"resume_from_run_id": "previous-run-id"}, "feature-branch"),
        ({"handoff_resumed": True}, "feature-branch"),
        ({}, None),
    ],
)
def test_clone_repository_uses_saved_branch_only_for_resumes(mocker, activity_environment, state, expected_branch):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state=state,
        _branch="feature-branch",
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        clone_repository_in_sandbox,
        CloneRepositoryInSandboxInput(
            context=context,
            sandbox_id="sandbox-id",
            repository="posthog/posthog",
            github_token="github-token",
            shallow_clone=True,
        ),
    )

    sandbox.clone_repository.assert_called_once_with(
        "posthog/posthog",
        github_token="github-token",
        shallow=True,
        branch=expected_branch,
    )


def test_resume_clone_falls_back_to_default_branch_when_saved_branch_is_missing(mocker, activity_environment):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state={"resume_from_run_id": "previous-run-id"},
        _branch="branch-from-a-sibling-repository",
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.side_effect = [
        ExecutionResult(
            stdout="",
            stderr=(
                "warning: Could not find remote branch branch-from-a-sibling-repository to clone.\n"
                "fatal: Remote branch branch-from-a-sibling-repository not found in upstream origin"
            ),
            exit_code=128,
        ),
        ExecutionResult(stdout="", stderr="", exit_code=0),
    ]
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        clone_repository_in_sandbox,
        CloneRepositoryInSandboxInput(
            context=context,
            sandbox_id="sandbox-id",
            repository="posthog/posthog",
            github_token="github-token",
            shallow_clone=True,
        ),
    )

    assert sandbox.clone_repository.call_args_list == [
        mocker.call(
            "posthog/posthog",
            github_token="github-token",
            shallow=True,
            branch="branch-from-a-sibling-repository",
        ),
        mocker.call(
            "posthog/posthog",
            github_token="github-token",
            shallow=True,
            branch=None,
        ),
    ]
