import json
import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotRunningError
from products.tasks.backend.logic.services.agentsh import build_audit_query_command
from products.tasks.backend.logic.services.sandbox import SandboxBase, get_sandbox_class_for_sandbox_id
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

logger = logging.getLogger(__name__)

MAX_LOG_SIZE = 50_000


@dataclass
class ReadSandboxLogsInput:
    sandbox_id: str
    run_id: str | None = None


SANDBOX_TERMINATED_MESSAGE = "Sandbox terminated before logs could be captured; no agent-server logs available."


def _read_agent_server_logs(sandbox: SandboxBase, sandbox_id: str) -> str:
    result = sandbox.execute(
        f"tail -c {MAX_LOG_SIZE} /tmp/agent-server.log 2>/dev/null || echo 'No log file found'",
        timeout_seconds=10,
    )
    logs = result.stdout.strip()
    if logs:
        logger.info(f"Sandbox {sandbox_id} agent-server logs:\n{logs}")
    return logs


def _collect_agentsh_diagnostics(sandbox: SandboxBase, sandbox_id: str, run_id: str | None) -> None:
    result = sandbox.execute(
        "cat /var/log/agentsh/agentsh.log 2>/dev/null || true",
        timeout_seconds=10,
    )
    agentsh_logs = result.stdout.strip()
    if not agentsh_logs:
        return
    logger.info(f"Sandbox {sandbox_id} agentsh diagnostics:\n{agentsh_logs}")
    if run_id:
        emit_agent_log(run_id, "debug", f"agentsh logs:\n{agentsh_logs[:2000]}")


def _format_audit_event(event: dict) -> str:
    decision = (event.get("effective_decision") or "").upper()
    domain = event.get("domain") or event.get("remote") or "unknown"
    rule = event.get("policy_rule") or ""
    etype = event.get("type") or ""
    return f"  {decision:5s} {domain} (rule: {rule}, type: {etype})"


def _collect_agentsh_audit_events(sandbox: SandboxBase, sandbox_id: str, run_id: str | None) -> None:
    """Collect agentsh audit events (network policy decisions). Best-effort; never raises."""
    try:
        result = sandbox.execute(build_audit_query_command(), timeout_seconds=10)
        audit_output = result.stdout.strip()
        if not audit_output or audit_output == "[]":
            return
        lines = [_format_audit_event(e) for e in json.loads(audit_output)]
        if not lines:
            return
        msg = "agentsh network events:\n" + "\n".join(lines)
        logger.info(f"Sandbox {sandbox_id} {msg}")
        if run_id:
            emit_agent_log(run_id, "debug", msg)
    except Exception:
        logger.debug("agentsh audit query failed for sandbox %s", sandbox_id, exc_info=True)


@activity.defn
@asyncify
def read_sandbox_logs(input: ReadSandboxLogsInput) -> str:
    """Read agent-server logs from the sandbox before it's destroyed."""
    with log_activity_execution(
        "read_sandbox_logs",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
            if not sandbox.is_running():
                logger.info(f"Sandbox {input.sandbox_id} already terminated; skipping log capture")
                return SANDBOX_TERMINATED_MESSAGE

            logs = _read_agent_server_logs(sandbox, input.sandbox_id)
            _collect_agentsh_diagnostics(sandbox, input.sandbox_id, input.run_id)
            _collect_agentsh_audit_events(sandbox, input.sandbox_id, input.run_id)
            return logs
        except SandboxNotRunningError:
            logger.info(f"Sandbox {input.sandbox_id} terminated mid-capture; no logs available")
            return SANDBOX_TERMINATED_MESSAGE
        except Exception as e:
            logger.warning(f"Failed to read sandbox logs: {e}")
            return f"Failed to read logs: {e}"
