import contextvars
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    get_primary_sandbox_jwt_kid,
)
from products.tasks.backend.logic.services.sandbox import AgentServerResult, SandboxBase
from products.tasks.backend.logic.services.sandbox_housekeeping import SandboxHousekeeping
from products.tasks.backend.logic.services.sandbox_usage import (
    measure_sandbox_billed_cpu_usage,
    measure_sandbox_cpu_usage,
    open_sandbox_session,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.metrics import StepTimer


@frozen
class PreparedSandboxConnection:
    credentials: AgentServerResult
    housekeeping: SandboxHousekeeping


def _get_connect_credentials(sandbox: SandboxBase) -> AgentServerResult:
    with StepTimer("sandbox_connect_credentials"):
        return sandbox.get_connect_credentials()


def prepare_sandbox_connection(sandbox: SandboxBase) -> PreparedSandboxConnection:
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"sandbox-connect-{sandbox.id}") as executor:
        credentials = executor.submit(contextvars.copy_context().run, _get_connect_credentials, sandbox)
        with StepTimer("sandbox_housekeeping"):
            housekeeping = sandbox.run_post_create_housekeeping()
        return PreparedSandboxConnection(credentials=credentials.result(), housekeeping=housekeeping)


def persist_sandbox_connection(
    *,
    run_id: str,
    sandbox: SandboxBase,
    credentials: AgentServerResult,
    sandbox_created_at: datetime | None,
    task_runtime: str | None,
    sandbox_backend: str | None = None,
    housekeeping: SandboxHousekeeping | None = None,
) -> str:
    with StepTimer("sandbox_jwt_key"):
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

    with StepTimer("persist_connection_state"):
        TaskRun.update_state_atomic(run_id, updates=sandbox_state)

    if housekeeping is None or housekeeping.cpu_usage_usec is None:
        with StepTimer("cpu_usage"):
            cpu_usage_attribution_usec, cpu_usage_attribution_measured_at = measure_sandbox_cpu_usage(sandbox)
        with StepTimer("billed_cpu_usage"):
            billed_cpu_usage_attribution_usec = measure_sandbox_billed_cpu_usage(sandbox)
    else:
        cpu_usage_attribution_usec = housekeeping.cpu_usage_usec
        cpu_usage_attribution_measured_at = housekeeping.cpu_usage_measured_at
        billed_cpu_usage_attribution_usec = housekeeping.billed_cpu_usage_usec
    with StepTimer("open_usage_session"):
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
