from typing import TYPE_CHECKING
from uuid import UUID

from celery import current_app

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.tasks.backend.logic.services.gateway_usage import record_generation_request

if TYPE_CHECKING:
    from posthog.llm.gateway_client import AIGatewayConfig

# Sent by name so the web worker never imports the task module, which drags the Temporal tree into it.
_SCHEDULE_GATEWAY_USAGE_TASK = "products.tasks.backend.tasks.tasks.schedule_task_run_gateway_usage"


def mint_private_gateway_token(
    *,
    team_id: int,
    user: str | None = None,
    expires_in_seconds: int | None = None,
    gateway_config: "AIGatewayConfig | None" = None,
    run_id: str | None = None,
) -> str:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        mint_scoped_token,
    )

    token = mint_scoped_token(
        ai_product="signals_scout",
        team_id=team_id,
        user=user,
        capture_mode="none",
        expires_in_seconds=expires_in_seconds,
        gateway_config=gateway_config,
        run_id=run_id,
    )
    if token is None:
        raise GatewayNotConfiguredError("Scout trials require a private AI gateway credential")
    return token


def revoke_private_gateway_token(token: str, *, gateway_config: "AIGatewayConfig | None" = None) -> None:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        revoke_scoped_token,
    )

    revoke_scoped_token(token, gateway_config=gateway_config)


def accept_generation_request(*, team_id: int, run_id: UUID, request_id: str) -> bool:
    recorded = record_generation_request(team_id=team_id, run_id=run_id, request_id=request_id)
    if recorded is None:
        return False
    if recorded:
        current_app.send_task(_SCHEDULE_GATEWAY_USAGE_TASK, kwargs={"run_id": str(run_id), "team_id": team_id})
    return True
