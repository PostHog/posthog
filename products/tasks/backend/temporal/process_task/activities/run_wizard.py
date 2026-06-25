import shlex
import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify
from posthog.utils import get_instance_region

from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

# Published npm package, pinned to @latest so cloud runs exercise the same build users install.
WIZARD_PACKAGE = "@posthog/wizard@latest"
WIZARD_RUN_TIMEOUT_SECONDS = 25 * 60


@dataclass
class RunWizardInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str


def _wizard_region() -> str:
    return "eu" if get_instance_region() == "EU" else "us"


def _build_wizard_command(repo_path: str, project_id: int, package: str) -> str:
    # The wizard reads its access token from the POSTHOG_WIZARD_API_KEY env var injected into the
    # sandbox (see provision_sandbox), so the token never appears on the command line. --headless
    # runs the published wizard non-interactively.
    return " ".join(
        [
            f"cd {shlex.quote(repo_path)} &&",
            f"npx --yes {shlex.quote(package)}",
            "--headless",
            "--install-dir .",
            f"--region {shlex.quote(_wizard_region())}",
            f"--project-id {shlex.quote(str(project_id))}",
        ]
    )


@activity.defn
@asyncify
def run_wizard(input: RunWizardInput) -> None:
    """Run the PostHog setup wizard in the sandbox before the agent starts.

    The wizard performs the real PostHog integration (modifies source, installs deps, writes
    posthog-setup-report.md), leaving the changes uncommitted in the working tree. The downstream
    agent then only has to commit them, open a PR, and keep it green. A non-zero exit fails the run
    rather than handing a half-integrated tree to the agent.
    """
    ctx = input.context

    with log_activity_execution(
        "run_wizard",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        org, repo = input.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        emit_agent_log(ctx.run_id, "info", "Running the PostHog setup wizard")
        sandbox = Sandbox.get_by_id(input.sandbox_id)
        config = ctx.wizard_config or {}
        package = config.get("package") or WIZARD_PACKAGE
        command = _build_wizard_command(repo_path, ctx.team_id, package)

        result = sandbox.execute(command, timeout_seconds=WIZARD_RUN_TIMEOUT_SECONDS)

        if result.stdout:
            emit_agent_log(ctx.run_id, "debug", result.stdout)
        if result.exit_code != 0:
            emit_agent_log(
                ctx.run_id, "error", f"PostHog setup wizard failed (exit {result.exit_code}): {result.stderr}"
            )
            raise RuntimeError(f"PostHog setup wizard failed with exit code {result.exit_code}")

        emit_agent_log(ctx.run_id, "info", "PostHog setup wizard completed")
