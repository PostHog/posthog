from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id
from products.tasks.backend.temporal.observability import log_activity_execution

HEALTH_PROBE_TIMEOUT_SECONDS = 20


@frozen
class ProbeSandboxAgentInput:
    sandbox_id: str
    run_id: str


@frozen
class ProbeSandboxAgentOutput:
    responsive: bool
    reason: str


@activity.defn
@asyncify
def probe_sandbox_agent(input: ProbeSandboxAgentInput) -> ProbeSandboxAgentOutput:
    with log_activity_execution("probe_sandbox_agent", sandbox_id=input.sandbox_id, run_id=input.run_id):
        try:
            sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
        except SandboxNotFoundError:
            return ProbeSandboxAgentOutput(responsive=False, reason="sandbox_not_found")
        if not sandbox.is_running():
            return ProbeSandboxAgentOutput(responsive=False, reason="sandbox_not_running")
        try:
            result = sandbox.execute(
                f"curl -sf --max-time 5 {sandbox.agent_server_health_url()}",
                timeout_seconds=HEALTH_PROBE_TIMEOUT_SECONDS,
            )
        except SandboxNotRunningError:
            return ProbeSandboxAgentOutput(responsive=False, reason="sandbox_not_running")
        except Exception as e:
            return ProbeSandboxAgentOutput(responsive=False, reason=f"probe_failed:{type(e).__name__}")
        if result.exit_code == 0:
            return ProbeSandboxAgentOutput(responsive=True, reason="agent_server_healthy")
        return ProbeSandboxAgentOutput(responsive=False, reason=f"agent_server_unhealthy:{result.exit_code}")
