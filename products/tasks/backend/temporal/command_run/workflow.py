from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from ..process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox
from ..process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)
from ..process_task.activities.provision_sandbox import (
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    PrepareSandboxForRepositoryInput,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    prepare_sandbox_for_repository,
)
from ..process_task.activities.update_task_run_status import UpdateTaskRunStatusInput, update_task_run_status
from . import constants
from .activities import CommitAndOpenPrInput, RunCommandInSandboxInput, commit_and_open_pr, run_command_in_sandbox


@dataclass
class CloudRunInput:
    run_id: str


@dataclass
class CloudRunOutput:
    success: bool
    pr_url: Optional[str] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None


class BaseCloudRunWorkflow(PostHogWorkflow):
    """The dumbest possible cloud run: provision a sandbox, clone the repo, do work, clean up.

    Knows nothing about commands, agents, or pull requests — only the lifecycle. Subclasses
    add capabilities by implementing `_execute()`. This class is intentionally not a Temporal
    workflow: the SDK requires the `@workflow.run` method to be defined directly on each
    concrete class (it is not inheritable), so concrete subclasses provide a thin `run()` that
    delegates to `_run()` here.
    """

    inputs_cls = CloudRunInput

    def __init__(self) -> None:
        self._context: Optional[TaskProcessingContext] = None

    @property
    def context(self) -> TaskProcessingContext:
        if self._context is None:
            raise RuntimeError("context accessed before being set")
        return self._context

    async def _run(self, input: CloudRunInput) -> CloudRunOutput:
        self._context = await workflow.execute_activity(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=input.run_id, create_pr=True),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        await self._update_status("in_progress")

        sandbox_id: Optional[str] = None
        try:
            sandbox_id = await self._provision_sandbox()
            pr_url = await self._execute(sandbox_id)
            await self._update_status("completed")
            return CloudRunOutput(success=True, pr_url=pr_url, sandbox_id=sandbox_id)
        except Exception as e:
            await self._update_status("failed", str(e))
            return CloudRunOutput(success=False, error=str(e), sandbox_id=sandbox_id)
        finally:
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    async def _execute(self, sandbox_id: str) -> Optional[str]:
        """Do the subclass-specific work inside the provisioned sandbox; return a PR URL if any."""
        raise NotImplementedError

    async def _provision_sandbox(self) -> str:
        prepared = await workflow.execute_activity(
            prepare_sandbox_for_repository,
            PrepareSandboxForRepositoryInput(context=self.context),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        created = await workflow.execute_activity(
            create_sandbox_for_repository,
            CreateSandboxForRepositoryInput(context=self.context, prepared=prepared),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if prepared.repository and not prepared.used_snapshot:
            await workflow.execute_activity(
                clone_repository_in_sandbox,
                CloneRepositoryInSandboxInput(
                    context=self.context,
                    sandbox_id=created.sandbox_id,
                    repository=prepared.repository,
                    github_token=prepared.github_token,
                    shallow_clone=prepared.shallow_clone,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        return created.sandbox_id

    async def _cleanup_sandbox(self, sandbox_id: str) -> None:
        await workflow.execute_activity(
            cleanup_sandbox,
            CleanupSandboxInput(sandbox_id=sandbox_id, run_id=self.context.run_id, complete_stream_on_cleanup=False),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _update_status(self, status: str, error_message: Optional[str] = None) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(run_id=self.context.run_id, status=status, error_message=error_message),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="process-command-run")
class CommandCloudRunWorkflow(BaseCloudRunWorkflow):
    """Run a CLI command against the cloned repo, then commit, push, and open a PR.

    Command and PR metadata come from overridable hook methods that default to reading
    the run's state, so named leaves can hardcode them without touching the lifecycle.
    """

    @workflow.run
    async def run(self, input: CloudRunInput) -> CloudRunOutput:
        return await self._run(input)

    async def _execute(self, sandbox_id: str) -> Optional[str]:
        ctx = self.context
        if not ctx.repository:
            raise RuntimeError("Command cloud run requires a repository")
        if ctx.github_integration_id is None:
            raise RuntimeError("Command cloud run requires a GitHub integration to open a PR")

        result = await workflow.execute_activity(
            run_command_in_sandbox,
            RunCommandInSandboxInput(
                run_id=ctx.run_id,
                sandbox_id=sandbox_id,
                command=self._command(ctx),
                repository=ctx.repository,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Command exited with non-zero status {result.exit_code}")

        pr = await workflow.execute_activity(
            commit_and_open_pr,
            CommitAndOpenPrInput(
                run_id=ctx.run_id,
                sandbox_id=sandbox_id,
                repository=ctx.repository,
                github_integration_id=ctx.github_integration_id,
                branch=self._branch_name(ctx),
                commit_message=self._commit_message(ctx),
                pr_title=self._pr_title(ctx),
                pr_body=self._pr_body(ctx),
                base_branch=self._base_branch(ctx),
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return pr.pr_url

    def _command(self, ctx: TaskProcessingContext) -> str:
        command = (ctx.state or {}).get("command")
        if not command:
            raise RuntimeError("No command configured for this run")
        return command

    def _pr_title(self, ctx: TaskProcessingContext) -> str:
        return (ctx.state or {}).get("pr_title") or "Automated change"

    def _pr_body(self, ctx: TaskProcessingContext) -> str:
        return (ctx.state or {}).get("pr_body") or ""

    def _base_branch(self, ctx: TaskProcessingContext) -> Optional[str]:
        return (ctx.state or {}).get("base_branch")

    def _commit_message(self, ctx: TaskProcessingContext) -> str:
        return (ctx.state or {}).get("commit_message") or self._pr_title(ctx)

    def _branch_name(self, ctx: TaskProcessingContext) -> str:
        # Deterministic (run_id is fixed for the workflow run) — never random/time-based.
        return f"cloud-run/{ctx.run_id}"


@workflow.defn(name="append-readme-command-run")
class AppendToReadmeCommandCloudRunWorkflow(CommandCloudRunWorkflow):
    """A named leaf: appends a marker line to the README and opens a fixed PR.

    Pure parameterization of the parent — it only overrides the hooks. The `run()` method
    is repeated because the Temporal SDK does not inherit `@workflow.run`.
    """

    @workflow.run
    async def run(self, input: CloudRunInput) -> CloudRunOutput:
        return await self._run(input)

    def _command(self, ctx: TaskProcessingContext) -> str:
        return constants.APPEND_README_COMMAND

    def _pr_title(self, ctx: TaskProcessingContext) -> str:
        return constants.APPEND_README_PR_TITLE

    def _pr_body(self, ctx: TaskProcessingContext) -> str:
        return constants.APPEND_README_PR_BODY
