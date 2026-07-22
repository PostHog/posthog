import shlex
import logging
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity
from temporalio.exceptions import ApplicationError, ApplicationErrorCategory

from posthog.temporal.common.utils import asyncify
from posthog.utils import get_instance_region

from products.tasks.backend.logic.services.sandbox import ExecutionResult, Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

# Published npm package, pinned to @latest so cloud runs exercise the same build users install.
WIZARD_PACKAGE = "@posthog/wizard@latest"

# Large repos can take ~45 min to integrate (observed p99.9 of real runs). The Temporal activity's
# start_to_close_timeout (see workflow._run_wizard_if_configured) must stay above this so the
# wizard's own timeout is what bounds the run, not the activity wrapper killing it early.
WIZARD_RUN_TIMEOUT_SECONDS = 45 * 60

# GNU `timeout` exit code when it kills a command. We wrap the wizard in `timeout` (see
# _build_wizard_command) so an over-budget run comes back as a normal result carrying this code —
# which we detect below — instead of the sandbox-level TimeoutError that would discard partial output.
WIZARD_TIMEOUT_EXIT_CODE = 124
# Sandbox-level backstop, above the shell `timeout` so the clean 124 path fires first; the sandbox
# only aborts the exec if `timeout` itself wedges.
_SANDBOX_EXEC_TIMEOUT_SECONDS = WIZARD_RUN_TIMEOUT_SECONDS + 120

# The wizard exits non-zero and prints this line when it can't classify the repo's framework. That's
# a user-input condition (the repo isn't something the wizard supports), not a system defect, so we
# detect it and surface a clean failure instead of the generic non-zero-exit RuntimeError.
WIZARD_FRAMEWORK_NOT_DETECTED_MARKER = "Could not auto-detect your framework"
# Error type surfaced on the non-retryable ApplicationError for this case, for downstream matching.
WIZARD_FRAMEWORK_NOT_DETECTED_ERROR_TYPE = "WizardFrameworkNotDetectedError"

# The wizard's console output is written OUTSIDE the cloned repo working tree so it can never be
# committed to the user's PR by mistake. The downstream agent reads it from this fixed path to
# understand what the wizard did (and why it failed).
WIZARD_OUTPUT_DIR = "/tmp/wizard-cloud-run"
WIZARD_OUTPUT_LOG_PATH = f"{WIZARD_OUTPUT_DIR}/wizard-output.log"

# The wizard's own verbose log — agent-level detail beyond stdout (e.g. which URL a failed API call
# hit). Fixed path inside the wizard (its src/utils/paths.ts: WIZARD_LOG_FILE). Lives only in the
# sandbox filesystem, so it's lost once the sandbox is torn down — we surface it in DEBUG below.
WIZARD_VERBOSE_LOG_PATH = "/tmp/posthog-wizard.log"


@dataclass
class RunWizardInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str


def _wizard_region() -> str:
    return "eu" if get_instance_region() == "EU" else "us"


def _format_wizard_output(result: ExecutionResult) -> str:
    sections = [f"PostHog setup wizard output (exit code {result.exit_code})"]
    if result.stdout:
        sections += ["", "=== stdout ===", result.stdout]
    if result.stderr:
        sections += ["", "=== stderr ===", result.stderr]
    return "\n".join(sections) + "\n"


def _wizard_failure_error(result: ExecutionResult) -> Exception | None:
    """Map a finished wizard run to the exception to raise, or None on success. Kept pure (no
    logging, no IO) so the exit-code handling is unit-testable without standing up a sandbox.

    A repo the wizard can't classify is a user-input condition, not a defect, so it becomes a
    benign, non-retryable ApplicationError that the interceptor keeps out of error tracking (see
    posthog/temporal/common/posthog_client.py). Genuinely unexpected non-zero exits stay a generic
    RuntimeError so they're still reported.
    """
    if result.exit_code == 0:
        return None
    if result.exit_code == WIZARD_TIMEOUT_EXIT_CODE:
        minutes = WIZARD_RUN_TIMEOUT_SECONDS // 60
        return RuntimeError(f"PostHog setup wizard timed out after {minutes} minutes")
    if WIZARD_FRAMEWORK_NOT_DETECTED_MARKER.lower() in (result.stdout or "").lower():
        return ApplicationError(
            "PostHog setup wizard could not auto-detect a supported framework in this repository, "
            "so there's nothing to integrate automatically.",
            type=WIZARD_FRAMEWORK_NOT_DETECTED_ERROR_TYPE,
            non_retryable=True,
            category=ApplicationErrorCategory.BENIGN,
        )
    # The wizard prints its fatal error to stdout (e.g. "Something went wrong: ..."); stderr is
    # mostly npm noise. Prefer the stdout tail so the real cause shows at error level.
    detail = (result.stdout or "").strip()[-2000:] or (result.stderr or "").strip()[-2000:]
    return RuntimeError(f"PostHog setup wizard failed (exit {result.exit_code}): {detail}")


def _build_wizard_command(repo_path: str, project_id: int) -> str:
    # The wizard reads its access token from the POSTHOG_WIZARD_API_KEY env var injected into the
    # sandbox (see provision_sandbox), so the token never appears on the command line.
    # --headless-DONOTUSE-EXPERIMENTAL runs the published wizard non-interactively.
    parts = [
        f"cd {shlex.quote(repo_path)} &&",
        # Wrap in `timeout` so an over-budget run exits WIZARD_TIMEOUT_EXIT_CODE (124) we can
        # detect, with partial output preserved. -k 30 escalates to SIGKILL 30s after SIGTERM.
        f"timeout -k 30 {WIZARD_RUN_TIMEOUT_SECONDS}",
        f"npx --yes {WIZARD_PACKAGE}",
        "--headless-DONOTUSE-EXPERIMENTAL",
        "--install-dir .",
        f"--region {shlex.quote(_wizard_region())}",
        f"--project-id {shlex.quote(str(project_id))}",
    ]

    if settings.DEBUG:
        # Local dev: pin the wizard to the same PostHog instance the sandbox itself reaches, instead
        # of letting it infer a cloud region from the access token (which fails for a locally-minted
        # token). POSTHOG_API_URL is injected into the sandbox env and already carries the provider's
        # in-container rewrite (e.g. http://host.docker.internal:8000 for the Docker sandbox, since
        # localhost/:8010 are unreachable from inside it), so expand it inside the container rather
        # than baking a host-side URL into the command.
        parts.append('--base-url "$POSTHOG_API_URL"')

    return " ".join(parts)


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
        command = _build_wizard_command(repo_path, ctx.team_id)

        result = sandbox.execute(command, timeout_seconds=_SANDBOX_EXEC_TIMEOUT_SECONDS)

        # Persist the wizard's output outside the repo tree so the agent can consult what happened
        # without any chance of committing it. Written before the exit-code check so a failed run
        # still leaves a record on disk for post-mortems.
        sandbox.execute(f"mkdir -p {shlex.quote(WIZARD_OUTPUT_DIR)}")
        sandbox.write_file(WIZARD_OUTPUT_LOG_PATH, _format_wizard_output(result).encode("utf-8"))

        if settings.DEBUG:
            # Pull the wizard's verbose log out of the sandbox before the workflow tears it down, so a
            # failed local run stays debuggable from the run's console log (it never reaches object
            # storage otherwise). `|| true` keeps a missing file — wizard exited before writing one —
            # from erroring the activity.
            verbose = sandbox.execute(f"cat {shlex.quote(WIZARD_VERBOSE_LOG_PATH)} 2>/dev/null || true")
            if verbose.stdout.strip():
                emit_agent_log(
                    ctx.run_id, "debug", f"wizard verbose log ({WIZARD_VERBOSE_LOG_PATH}):\n{verbose.stdout}"
                )

        if result.stdout:
            emit_agent_log(ctx.run_id, "debug", result.stdout)

        error = _wizard_failure_error(result)
        if error is not None:
            # ApplicationError.message is the bare text; str() would prepend the error type, which
            # doesn't belong in the user-facing run log.
            emit_agent_log(ctx.run_id, "error", getattr(error, "message", None) or str(error))
            raise error

        emit_agent_log(ctx.run_id, "info", "PostHog setup wizard completed")
