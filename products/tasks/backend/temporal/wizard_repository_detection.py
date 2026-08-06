"""Repository detection workflow.

Provision a sandbox, clone the repository, run the wizard detection program
the task's `kind` selects, tear the sandbox down. The wizard posts its report
to the wizard product's repository-detections API itself, so nothing flows
back through this workflow except run status. A sibling of ProcessTaskWorkflow
(its activities, none of its orchestration): no agent, no PR, no signals.
"""

import json
import shlex
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

import temporalio.exceptions
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.constants import WIZARD_REPOSITORY_DETECTION_PROGRAMS
from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.activities import (
    CleanupSandboxInput,
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    PrepareSandboxForRepositoryInput,
    UpdateTaskRunStatusInput,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    get_task_processing_context,
    prepare_sandbox_for_repository,
    update_task_run_status,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
)
from products.tasks.backend.temporal.process_task.activities.run_wizard import (
    WIZARD_PACKAGE,
    WIZARD_RUN_TIMEOUT_SECONDS,
    WIZARD_TIMEOUT_EXIT_CODE,
    WIZARD_VERBOSE_LOG_PATH,
    _wizard_region,
)

logger = logging.getLogger(__name__)

# Sandbox-level backstop, above the shell `timeout` so the clean 124 path fires first.
_SANDBOX_EXEC_TIMEOUT_SECONDS = WIZARD_RUN_TIMEOUT_SECONDS + 120


@dataclass
class RunWizardRepositoryDetectionInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str


def _build_wizard_repository_detection_command(kind: str, repo_path: str, project_id: int, repository: str) -> str:
    program = WIZARD_REPOSITORY_DETECTION_PROGRAMS.get(kind)
    if program is None:
        raise ValueError(f"Unknown detection kind: {kind}")
    # The wizard reads its token from the POSTHOG_WIZARD_API_KEY env var provisioning injects, so
    # it never appears on the command line. No headless flag: detection subcommands don't declare
    # it, and yargs rejects flags a command doesn't declare.
    parts = [
        f"cd {shlex.quote(repo_path)} &&",
        # `timeout` makes an over-budget run exit WIZARD_TIMEOUT_EXIT_CODE (124); -k escalates to SIGKILL.
        f"timeout -k 30 {WIZARD_RUN_TIMEOUT_SECONDS}",
        f"npx --yes {WIZARD_PACKAGE}",
        *program,
        # The sandbox clone's origin remote carries a token URL, so pass the repository explicitly.
        f"--repository {shlex.quote(repository)}",
        "--install-dir .",
        f"--region {shlex.quote(_wizard_region())}",
        f"--project-id {shlex.quote(str(project_id))}",
    ]

    if settings.DEBUG:
        # Local dev: pin the wizard to the PostHog instance the sandbox reaches (see run_wizard).
        parts.append('--base-url "$POSTHOG_API_URL"')

    return " ".join(parts)


@activity.defn
@asyncify
def run_wizard_repository_detection(input: RunWizardRepositoryDetectionInput) -> None:
    """Run the wizard's detection program in the sandbox. The wizard posts its report (or
    failure) itself; this activity surfaces console output and fails the run on non-zero exit."""
    ctx = input.context
    kind = (ctx.wizard_config or {}).get("kind") or ""

    with log_activity_execution(
        "run_wizard_repository_detection",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        org, repo = input.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        emit_agent_log(ctx.run_id, "info", f"Running repository detection ({kind})")
        sandbox = Sandbox.get_by_id(input.sandbox_id)
        command = _build_wizard_repository_detection_command(kind, repo_path, ctx.team_id, input.repository)

        result = sandbox.execute(command, timeout_seconds=_SANDBOX_EXEC_TIMEOUT_SECONDS)

        if settings.DEBUG:
            # Surface the wizard's verbose log before teardown so failed local runs stay
            # debuggable from the run's console log (see run_wizard for the rationale).
            verbose = sandbox.execute(f"cat {shlex.quote(WIZARD_VERBOSE_LOG_PATH)} 2>/dev/null || true")
            if verbose.stdout.strip():
                emit_agent_log(
                    ctx.run_id, "debug", f"wizard verbose log ({WIZARD_VERBOSE_LOG_PATH}):\n{verbose.stdout}"
                )

        if result.stdout:
            emit_agent_log(ctx.run_id, "debug", result.stdout)
        if result.exit_code == WIZARD_TIMEOUT_EXIT_CODE:
            minutes = WIZARD_RUN_TIMEOUT_SECONDS // 60
            raise RuntimeError(f"Repository detection timed out after {minutes} minutes")
        if result.exit_code != 0:
            detail = (result.stdout or "").strip()[-2000:] or (result.stderr or "").strip()[-2000:]
            emit_agent_log(ctx.run_id, "error", f"Repository detection failed (exit {result.exit_code}): {detail}")
            raise RuntimeError(f"Repository detection failed (exit {result.exit_code}): {detail}")

        emit_agent_log(ctx.run_id, "info", "Repository detection completed")


@dataclass
class WizardRepositoryDetectionInput:
    run_id: str


@dataclass
class WizardRepositoryDetectionOutput:
    success: bool
    error: str | None = None
    sandbox_id: str | None = None


@workflow.defn(name="wizard-repository-detection")
class WizardRepositoryDetectionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WizardRepositoryDetectionInput:
        loaded = json.loads(inputs[0])
        return WizardRepositoryDetectionInput(run_id=loaded["run_id"])

    @workflow.run
    async def run(self, input: WizardRepositoryDetectionInput) -> WizardRepositoryDetectionOutput:
        sandbox_id: str | None = None
        try:
            # Inside the try so a context failure still terminalizes the run instead of leaving
            # it in QUEUED for the 24h killer.
            context: TaskProcessingContext = await workflow.execute_activity(
                get_task_processing_context,
                GetTaskProcessingContextInput(run_id=input.run_id, create_pr=False),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            await self._update_status(input.run_id, "in_progress")

            repository = context.repository
            if not repository:
                raise RuntimeError("Repository detection requires a task with a repository")

            prepared = await workflow.execute_activity(
                prepare_sandbox_for_repository,
                PrepareSandboxForRepositoryInput(context=context),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            created = await workflow.execute_activity(
                create_sandbox_for_repository,
                CreateSandboxForRepositoryInput(context=context, prepared=prepared),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            sandbox_id = created.sandbox_id

            used_snapshot = created.used_snapshot if created.used_snapshot is not None else prepared.used_snapshot
            if not used_snapshot:
                await workflow.execute_activity(
                    clone_repository_in_sandbox,
                    CloneRepositoryInSandboxInput(
                        context=context,
                        sandbox_id=sandbox_id,
                        repository=repository,
                        github_token=prepared.github_token,
                        shallow_clone=prepared.shallow_clone,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

            await workflow.execute_activity(
                run_wizard_repository_detection,
                RunWizardRepositoryDetectionInput(context=context, sandbox_id=sandbox_id, repository=repository),
                # Above WIZARD_RUN_TIMEOUT_SECONDS so the wizard's own timeout bounds the run.
                # No retries: a retry doubles the scan cost, so fail and let the user re-trigger.
                start_to_close_timeout=timedelta(minutes=50),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            await self._update_status(input.run_id, "completed")
            return WizardRepositoryDetectionOutput(success=True, sandbox_id=sandbox_id)

        except Exception as e:
            # str(ActivityError) is Temporal's opaque wrapper; surface the cause instead.
            cause = e.cause if isinstance(e, temporalio.exceptions.ActivityError) else None
            message = truncate_error_message(
                getattr(cause, "message", None) or (str(cause) if cause else None) or str(e)
            )
            await self._update_status(input.run_id, "failed", error_message=message, error_type=type(e).__name__)
            return WizardRepositoryDetectionOutput(success=False, error=message, sandbox_id=sandbox_id)

        finally:
            if sandbox_id is not None:
                await workflow.execute_activity(
                    cleanup_sandbox,
                    CleanupSandboxInput(sandbox_id=sandbox_id, run_id=input.run_id, complete_stream_on_cleanup=True),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

    async def _update_status(
        self, run_id: str, status: str, *, error_message: str | None = None, error_type: str | None = None
    ) -> None:
        await workflow.execute_activity(
            update_task_run_status,
            UpdateTaskRunStatusInput(run_id=run_id, status=status, error_message=error_message, error_type=error_type),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
