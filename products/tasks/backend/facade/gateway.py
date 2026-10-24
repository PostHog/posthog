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


def resolve_sandbox_ai_product(origin_product: str | None, ai_stage: str | None, *, internal: bool = False) -> str:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        resolve_sandbox_ai_product as resolve_product,
    )

    return resolve_product(origin_product, ai_stage, internal=internal)


def sandbox_product_routed(ai_product: str, ai_stage: str | None, products_csv: str) -> bool:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        sandbox_product_routed as product_routed,
    )

    return product_routed(ai_product, ai_stage, products_csv)


def token_cap_usd(team_id: int, ai_product: str) -> str:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        token_cap_usd as product_token_cap,
    )

    return product_token_cap(team_id, ai_product)


def mint_scoped_token(
    *, ai_product: str, team_id: int, user: str | None = None, expires_in_seconds: int | None = None
) -> str | None:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        mint_scoped_token as mint_token,
    )

    return mint_token(ai_product=ai_product, team_id=team_id, user=user, expires_in_seconds=expires_in_seconds)


def revoke_scoped_token(token: str) -> None:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 -- breaks the Temporal aggregate's import cycle through process_task.utils
        revoke_scoped_token as revoke_token,
    )

    revoke_token(token)


def accept_generation_request(*, team_id: int, run_id: UUID, request_id: str) -> bool:
    try:
        recorded = record_generation_request(team_id=team_id, run_id=run_id, request_id=request_id)
    except TaskRun.DoesNotExist:
        return False
    if recorded:
        schedule_gateway_usage(team_id=team_id, run_id=run_id)
    return True
