import json
import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)

MAX_LOG_SIZE = 50_000


@dataclass
class ReadSandboxLogsInput:
    sandbox_id: str
    run_id: str | None = None


@activity.defn
@asyncify
def read_sandbox_logs(input: ReadSandboxLogsInput) -> str:
    """Read agent-server logs from the sandbox before it's destroyed."""
    with log_activity_execution(
        "read_sandbox_logs",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
            result = sandbox.execute(
                f"tail -c {MAX_LOG_SIZE} /tmp/agent-server.log 2>/dev/null || echo 'No log file found'",
                timeout_seconds=10,
            )
            logs = result.stdout.strip()
            if logs:
                logger.info(f"Sandbox {input.sandbox_id} agent-server logs:\n{logs}")

            # agentsh diagnostics
            agentsh_result = sandbox.execute(
                "cat /var/log/agentsh/agentsh.log 2>/dev/null || true",
                timeout_seconds=10,
            )
            agentsh_logs = agentsh_result.stdout.strip()
            if agentsh_logs:
                logger.info(f"Sandbox {input.sandbox_id} agentsh diagnostics:\n{agentsh_logs}")
                if input.run_id:
                    from products.tasks.backend.temporal.observability import emit_agent_log

                    emit_agent_log(input.run_id, "debug", f"agentsh logs:\n{agentsh_logs[:2000]}")

            # agentsh audit events (network policy decisions)
            try:
                from products.tasks.backend.services.agentsh import build_audit_query_command

                audit_result = sandbox.execute(build_audit_query_command(), timeout_seconds=10)
                audit_output = audit_result.stdout.strip()
                if audit_output and audit_output != "[]":
                    events = json.loads(audit_output)
                    lines = []
                    for e in events:
                        decision = (e.get("effective_decision") or "").upper()
                        domain = e.get("domain") or e.get("remote") or "unknown"
                        rule = e.get("policy_rule") or ""
                        etype = e.get("type") or ""
                        lines.append(f"  {decision:5s} {domain} (rule: {rule}, type: {etype})")
                    if lines:
                        msg = "agentsh network events:\n" + "\n".join(lines)
                        logger.info(f"Sandbox {input.sandbox_id} {msg}")
                        if input.run_id:
                            emit_agent_log(input.run_id, "debug", msg)
            except Exception:
                logger.debug("agentsh audit query failed for sandbox %s", input.sandbox_id, exc_info=True)

            return logs
        except Exception as e:
            logger.warning(f"Failed to read sandbox logs: {e}")
            return f"Failed to read logs: {e}"
