from typing import Any

from products.tasks.backend.agent_proxy_callback import AgentProxyCallbackDispatcher, CallbackOutcome, CallbackRequest
from products.tasks.backend.feature_flags import run_agent_sends_callbacks
from products.tasks.backend.logic.services.connection_token import SandboxEventIngestTokenPayload
from products.tasks.backend.models import TaskRun


def dispatch_agent_callback(
    *, run_id: str, task_id: str, team_id: int, body: dict[str, Any], data: dict[str, Any]
) -> CallbackOutcome:
    state = TaskRun.objects.filter(id=run_id, task_id=task_id, team_id=team_id).values_list("state", flat=True).first()
    if not run_agent_sends_callbacks(state):
        return CallbackOutcome(status=403, error="The agent-proxy sends the callbacks for this run")
    callback = CallbackRequest(
        run_id=run_id,
        claims=SandboxEventIngestTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id, sandbox_id=None),
        body=body,
        data={**data, "task_id": task_id, "team_id": team_id},
    )
    return AgentProxyCallbackDispatcher(callback).dispatch()
