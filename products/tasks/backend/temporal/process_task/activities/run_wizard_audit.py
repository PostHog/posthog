import json
import shlex
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext
from .run_wizard import WIZARD_OUTPUT_DIR, WIZARD_PACKAGE, _format_wizard_output, _wizard_region

logger = logging.getLogger(__name__)

# The audit is read-only and much smaller than the integration run.
AUDIT_RUN_TIMEOUT_SECONDS = 20 * 60
_SANDBOX_EXEC_TIMEOUT_SECONDS = AUDIT_RUN_TIMEOUT_SECONDS + 120

# Structured check ledger the wizard audit skill maintains in the install dir
# (wizard repo: AUDIT_CHECKS_FILE) — a JSON array of {id, area, label, status, file?, details?}.
AUDIT_CHECKS_FILE = ".posthog-audit-checks.json"

AUDIT_OUTPUT_LOG_PATH = f"{WIZARD_OUTPUT_DIR}/wizard-audit-output.log"

# TaskRun.output key the checks are persisted under; the GitHub merge webhook reads it to feed
# the signals wizard setup review.
WIZARD_AUDIT_CHECKS_OUTPUT_KEY = "wizard_audit_checks"

# Ledger bookkeeping rows that aren't setup findings.
_NON_FINDING_CHECK_IDS = frozenset({"write-report", "upload-notebook"})

_MAX_CHECKS = 50
_MAX_DETAILS_CHARS = 2000


@dataclass
class RunWizardAuditInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str


def _build_audit_command(repo_path: str, project_id: int) -> str:
    # Same shape as the integration run (see run_wizard._build_wizard_command): token comes from
    # the sandbox env (POSTHOG_WIZARD_API_KEY), `audit all` is the comprehensive audit leaf.
    parts = [
        f"cd {shlex.quote(repo_path)} &&",
        f"timeout -k 30 {AUDIT_RUN_TIMEOUT_SECONDS}",
        f"npx --yes {WIZARD_PACKAGE}",
        "audit all",
        "--headless-DONOTUSE-EXPERIMENTAL",
        "--install-dir .",
        f"--region {shlex.quote(_wizard_region())}",
        f"--project-id {shlex.quote(str(project_id))}",
    ]
    if settings.DEBUG:
        parts.append('--base-url "$POSTHOG_API_URL"')
    return " ".join(parts)


def _parse_checks(raw: str) -> list[dict[str, Any]]:
    """Validate and prune the audit ledger down to persistable finding rows."""
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        return []
    checks: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        check_id, label, status = entry.get("id"), entry.get("label"), entry.get("status")
        if not (isinstance(check_id, str) and isinstance(label, str) and isinstance(status, str)):
            continue
        if check_id in _NON_FINDING_CHECK_IDS:
            continue
        checks.append(
            {
                "id": check_id,
                "area": entry.get("area") if isinstance(entry.get("area"), str) else None,
                "label": label,
                "status": status,
                "file": entry.get("file") if isinstance(entry.get("file"), str) else None,
                "details": str(entry.get("details"))[:_MAX_DETAILS_CHARS] if entry.get("details") else None,
            }
        )
        if len(checks) >= _MAX_CHECKS:
            break
    return checks


def _persist_checks(run_id: str, checks: list[dict[str, Any]]) -> None:
    from products.tasks.backend.models import TaskRun

    with transaction.atomic():
        run = TaskRun.objects.select_for_update().get(id=run_id)
        output = run.output if isinstance(run.output, dict) else {}
        run.output = {**output, WIZARD_AUDIT_CHECKS_OUTPUT_KEY: checks}
        run.save(update_fields=["output", "updated_at"])


@activity.defn
@asyncify
def run_wizard_audit(input: RunWizardAuditInput) -> None:
    """Run the wizard's setup audit in the sandbox right after the integration run.

    The audit skill reviews the fresh integration (identify usage, capture quality, proxy, growth
    events, ...) and maintains a structured check ledger in the working tree; the checks are
    persisted onto TaskRun.output so the merge webhook can turn the failing ones into signals.
    Best-effort by design: a broken or timed-out audit only means no setup-review signals — it
    must never fail the wizard run itself, so this activity swallows every error.
    """
    ctx = input.context

    with log_activity_execution(
        "run_wizard_audit",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        try:
            org, repo = input.repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

            emit_agent_log(ctx.run_id, "info", "Running the PostHog setup audit")
            sandbox = Sandbox.get_by_id(input.sandbox_id)

            result = sandbox.execute(
                _build_audit_command(repo_path, ctx.team_id), timeout_seconds=_SANDBOX_EXEC_TIMEOUT_SECONDS
            )

            # Keep a record outside the repo tree (never committable), like the integration run.
            sandbox.execute(f"mkdir -p {shlex.quote(WIZARD_OUTPUT_DIR)}")
            sandbox.write_file(AUDIT_OUTPUT_LOG_PATH, _format_wizard_output(result).encode("utf-8"))

            if result.exit_code != 0:
                detail = (result.stdout or "").strip()[-2000:] or (result.stderr or "").strip()[-2000:]
                emit_agent_log(ctx.run_id, "warn", f"Setup audit failed (exit {result.exit_code}): {detail}")
                return

            ledger = sandbox.execute(f"cat {shlex.quote(f'{repo_path}/{AUDIT_CHECKS_FILE}')} 2>/dev/null || true")
            checks = _parse_checks(ledger.stdout) if ledger.stdout.strip() else []
            if not checks:
                emit_agent_log(ctx.run_id, "warn", "Setup audit produced no check ledger")
                return

            _persist_checks(ctx.run_id, checks)
            emit_agent_log(ctx.run_id, "info", f"Setup audit completed with {len(checks)} checks")
        except Exception:
            logger.warning("run_wizard_audit_failed", exc_info=True)
            emit_agent_log(ctx.run_id, "warn", "Setup audit did not complete; skipping setup-review signals")
