from typing import Any

from products.tasks.backend.agent_proxy_callback import AgentProxyCallbackDispatcher, CallbackOutcome, CallbackRequest
from products.tasks.backend.feature_flags import run_agent_sends_callbacks
from products.tasks.backend.logic.services.connection_token import SandboxEventIngestTokenPayload
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import get_tasks_cache

SEQUENCED_TURN_KINDS = frozenset({"awaiting_input", "turn_failed"})
TURN_DEDUPE_TTL_SECONDS = 24 * 60 * 60
TURN_CLAIM_TTL_SECONDS = 60
TURN_CLAIM_PENDING = "pending"
TURN_CLAIM_DELIVERED = "delivered"


def dispatch_agent_callback(
    *, run_id: str, task_id: str, team_id: int, body: dict[str, Any], data: dict[str, Any]
) -> CallbackOutcome:
    state = TaskRun.objects.filter(id=run_id, task_id=task_id, team_id=team_id).values_list("state", flat=True).first()
    if not run_agent_sends_callbacks(state):
        return CallbackOutcome(status=403, error="The agent-proxy sends the callbacks for this run")
    dedupe_key = _turn_dedupe_key(run_id, data)
    cache = get_tasks_cache()
    if dedupe_key is not None and not cache.add(dedupe_key, TURN_CLAIM_PENDING, timeout=TURN_CLAIM_TTL_SECONDS):
        if cache.get(dedupe_key) == TURN_CLAIM_DELIVERED:
            return CallbackOutcome(dispatched=True)
        return CallbackOutcome(status=503, error="This turn result is still being delivered")
    callback = CallbackRequest(
        run_id=run_id,
        claims=SandboxEventIngestTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id, sandbox_id=None),
        body=body,
        data={**data, "task_id": task_id, "team_id": team_id},
    )
    outcome = AgentProxyCallbackDispatcher(callback).dispatch()
    if dedupe_key is not None:
        if outcome.status == 200 and outcome.error is None:
            cache.set(dedupe_key, TURN_CLAIM_DELIVERED, timeout=TURN_DEDUPE_TTL_SECONDS)
        else:
            cache.delete(dedupe_key)
    return outcome


def _turn_dedupe_key(run_id: str, data: dict[str, Any]) -> str | None:
    sequence = data.get("sequence")
    if data["kind"] not in SEQUENCED_TURN_KINDS or sequence is None:
        return None
    return f"tasks:agent_callback:{run_id}:{data['kind']}:{sequence}"
