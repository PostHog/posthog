from typing import TYPE_CHECKING
from uuid import UUID

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.tasks.backend.logic.services.gateway_usage import record_generation_request, schedule_gateway_usage
from products.tasks.backend.models import TaskRun

if TYPE_CHECKING:
    from posthog.llm.gateway_client import AIGatewayConfig


def mint_private_gateway_token(
    *,
    team_id: int,
    user: str | None = None,
    expires_in_seconds: int | None = None,
    gateway_config: "AIGatewayConfig | None" = None,
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
    try:
        recorded = record_generation_request(team_id=team_id, run_id=run_id, request_id=request_id)
    except TaskRun.DoesNotExist:
        return False
    if recorded:
        schedule_gateway_usage(team_id=team_id, run_id=run_id)
    return True
