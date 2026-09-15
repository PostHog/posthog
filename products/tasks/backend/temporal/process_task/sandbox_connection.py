from datetime import datetime
from typing import Any

from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    get_primary_sandbox_jwt_kid,
)
from products.tasks.backend.logic.services.sandbox import AgentServerResult, SandboxBase
from products.tasks.backend.logic.services.sandbox_usage import (
    measure_sandbox_billed_cpu_usage,
    measure_sandbox_cpu_usage,
    open_sandbox_session,
)
from products.tasks.backend.models import TaskRun


def persist_sandbox_connection(
    *,
    run_id: str,
    sandbox: SandboxBase,
    credentials: AgentServerResult,
    sandbox_created_at: datetime | None,
    task_runtime: str | None,
    sandbox_backend: str | None = None,
) -> str:
    jwt_kid = get_primary_sandbox_jwt_kid()
    sandbox_state: dict[str, Any] = {
        "sandbox_id": sandbox.id,
        "sandbox_url": credentials.url,
        SANDBOX_JWT_STATE_KID_KEY: jwt_kid,
    }
    if sandbox_backend is not None:
        sandbox_state["sandbox_backend"] = sandbox_backend
    if credentials.token:
        sandbox_state["sandbox_connect_token"] = credentials.token

    TaskRun.update_state_atomic(run_id, updates=sandbox_state)

    cpu_usage_attribution_usec, cpu_usage_attribution_measured_at = measure_sandbox_cpu_usage(sandbox)
    billed_cpu_usage_attribution_usec = measure_sandbox_billed_cpu_usage(sandbox)
    open_sandbox_session(
        run_id=run_id,
        sandbox_id=sandbox.id,
        config=sandbox.config,
        sandbox_created_at=sandbox_created_at,
        cpu_usage_attribution_usec=cpu_usage_attribution_usec,
        billed_cpu_usage_attribution_usec=billed_cpu_usage_attribution_usec,
        cpu_usage_attribution_measured_at=cpu_usage_attribution_measured_at,
        required=task_runtime == "pi",
    )
    return jwt_kid
