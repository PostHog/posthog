import pytest
from unittest.mock import AsyncMock

from products.tasks.backend.temporal.command_run import (
    constants,
    workflow as command_run_workflow_module,
)
from products.tasks.backend.temporal.command_run.activities import OpenPrOutput, RunCommandOutput
from products.tasks.backend.temporal.command_run.workflow import (
    AppendToReadmeCommandCloudRunWorkflow,
    CloudRunInput,
    CommandCloudRunWorkflow,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


def _build_context(*, repository="posthog/hedgebox", github_integration_id=123, state=None) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=github_integration_id,
        repository=repository,
        distinct_id="distinct-id",
        state=state or {},
    )


class TestCommandCloudRunWorkflow:
    def test_workflow_definitions_are_registered_with_run_methods(self):
        # The @workflow.run method must live on each concrete class (not inherited).
        assert CommandCloudRunWorkflow.get_name() == "process-command-run"
        assert AppendToReadmeCommandCloudRunWorkflow.get_name() == "append-readme-command-run"

    @pytest.mark.parametrize(
        "state, expected_command, expected_title, expected_body, expected_base",
        [
            (
                {"command": "make migrate", "pr_title": "Run migrations", "pr_body": "body", "base_branch": "main"},
                "make migrate",
                "Run migrations",
                "body",
                "main",
            ),
            ({"command": "echo hi"}, "echo hi", "Automated change", "", None),
        ],
    )
    def test_command_workflow_hooks_read_state(
        self, state, expected_command, expected_title, expected_body, expected_base
    ):
        wf = CommandCloudRunWorkflow()
        ctx = _build_context(state=state)
        assert wf._command(ctx) == expected_command
        assert wf._pr_title(ctx) == expected_title
        assert wf._pr_body(ctx) == expected_body
        assert wf._base_branch(ctx) == expected_base
        assert wf._branch_name(ctx) == "cloud-run/run-id"

    def test_command_workflow_requires_a_command_in_state(self):
        wf = CommandCloudRunWorkflow()
        with pytest.raises(RuntimeError, match="No command configured"):
            wf._command(_build_context(state={}))

    def test_append_readme_leaf_hardcodes_command_and_pr_metadata(self):
        wf = AppendToReadmeCommandCloudRunWorkflow()
        ctx = _build_context(state={})  # leaf ignores state entirely
        assert wf._command(ctx) == constants.APPEND_README_COMMAND
        assert wf._pr_title(ctx) == constants.APPEND_README_PR_TITLE
        assert wf._pr_body(ctx) == constants.APPEND_README_PR_BODY

    async def test_run_marks_completed_and_always_cleans_up(self, monkeypatch):
        wf = CommandCloudRunWorkflow()
        statuses: list[str] = []

        monkeypatch.setattr(wf, "_provision_sandbox", AsyncMock(return_value="sandbox-1"))
        monkeypatch.setattr(wf, "_execute", AsyncMock(return_value="https://github.com/o/r/pull/1"))
        monkeypatch.setattr(wf, "_update_status", AsyncMock(side_effect=lambda status, *a: statuses.append(status)))
        cleanup_mock = AsyncMock()
        monkeypatch.setattr(wf, "_cleanup_sandbox", cleanup_mock)
        monkeypatch.setattr(
            command_run_workflow_module.workflow,
            "execute_activity",
            AsyncMock(return_value=_build_context()),
        )

        result = await wf.run(CloudRunInput(run_id="run-id"))

        assert result.success is True
        assert result.pr_url == "https://github.com/o/r/pull/1"
        assert statuses == ["in_progress", "completed"]
        cleanup_mock.assert_awaited_once_with("sandbox-1")

    async def test_run_marks_failed_and_cleans_up_on_error(self, monkeypatch):
        wf = CommandCloudRunWorkflow()
        statuses: list[str] = []

        monkeypatch.setattr(wf, "_provision_sandbox", AsyncMock(return_value="sandbox-1"))
        monkeypatch.setattr(wf, "_execute", AsyncMock(side_effect=RuntimeError("command failed")))
        monkeypatch.setattr(wf, "_update_status", AsyncMock(side_effect=lambda status, *a: statuses.append(status)))
        cleanup_mock = AsyncMock()
        monkeypatch.setattr(wf, "_cleanup_sandbox", cleanup_mock)
        monkeypatch.setattr(
            command_run_workflow_module.workflow,
            "execute_activity",
            AsyncMock(return_value=_build_context()),
        )

        result = await wf.run(CloudRunInput(run_id="run-id"))

        assert result.success is False
        assert result.error == "command failed"
        assert statuses == ["in_progress", "failed"]
        cleanup_mock.assert_awaited_once_with("sandbox-1")

    async def test_execute_runs_command_then_opens_pr(self, monkeypatch):
        wf = CommandCloudRunWorkflow()
        wf._context = _build_context(state={"command": "echo hi"})
        calls = []

        async def fake_execute_activity(fn, arg, **kwargs):
            calls.append(fn.__name__)
            if fn.__name__ == "run_command_in_sandbox":
                return RunCommandOutput(exit_code=0)
            return OpenPrOutput(created_pr=True, pr_url="https://github.com/o/r/pull/9", commit_sha="abc")

        monkeypatch.setattr(command_run_workflow_module.workflow, "execute_activity", fake_execute_activity)

        pr_url = await wf._execute("sandbox-1")

        assert pr_url == "https://github.com/o/r/pull/9"
        assert calls == ["run_command_in_sandbox", "commit_and_open_pr"]

    async def test_execute_raises_on_nonzero_exit_and_skips_pr(self, monkeypatch):
        wf = CommandCloudRunWorkflow()
        wf._context = _build_context(state={"command": "false"})
        calls = []

        async def fake_execute_activity(fn, arg, **kwargs):
            calls.append(fn.__name__)
            return RunCommandOutput(exit_code=1)

        monkeypatch.setattr(command_run_workflow_module.workflow, "execute_activity", fake_execute_activity)

        with pytest.raises(RuntimeError, match="non-zero status"):
            await wf._execute("sandbox-1")
        assert calls == ["run_command_in_sandbox"]

    @pytest.mark.parametrize(
        "repository, github_integration_id, match",
        [
            (None, 123, "requires a repository"),
            ("posthog/hedgebox", None, "requires a GitHub integration"),
        ],
    )
    async def test_execute_requires_repository_and_integration(self, repository, github_integration_id, match):
        wf = CommandCloudRunWorkflow()
        wf._context = _build_context(
            repository=repository, github_integration_id=github_integration_id, state={"command": "x"}
        )
        with pytest.raises(RuntimeError, match=match):
            await wf._execute("sandbox-1")
