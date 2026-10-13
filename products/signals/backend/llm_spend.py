import asyncio
from collections.abc import Awaitable
from decimal import Decimal

import structlog
from anthropic import APIResponseValidationError
from anthropic.types import Message
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import fetch_gateway_cost
from posthog.sync import database_sync_to_async

from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend import record_llm_spend

logger = structlog.get_logger(__name__)


@frozen
class PricedGeneration:
    response: Message
    spend: Decimal | None


async def _settle_generation(
    request_id: str | None,
    *,
    gateway: AIGatewayConfig | None,
    team_id: int | None,
    signal_id: str | None,
    stage: str,
) -> Decimal | None:
    cost_microusd = None
    try:
        if gateway is None or not request_id or team_id is None or signal_id is None:
            return None
        delay = 0.01
        while True:
            cost = await fetch_gateway_cost(request_id, base_url=gateway.url, api_key=gateway.api_key)
            if cost is not None:
                cost_microusd = cost.cost_microusd
                return cost_to_spend(cost_microusd)
            if activity.in_activity():
                activity.heartbeat()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 1.0)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage=stage, team_id=team_id, signal_id=signal_id)
        return None
    finally:
        await database_sync_to_async(record_llm_spend)(
            request_id,
            token_cost_microusd=cost_microusd,
            team_id=team_id,
            signal_id=signal_id,
            stage=stage,
        )


async def generate_with_spend(
    generation: Awaitable[Message],
    *,
    gateway: AIGatewayConfig | None,
    team_id: int | None,
    signal_id: str | None,
    stage: str,
) -> PricedGeneration:
    """Generate once, then wait for its gateway usage. Spend is in USD cents.

    Polling stays in the calling activity and is cancellable by its lifetime.
    Missing request IDs preserve the response and mark its stage unaccounted.
    """
    try:
        response = await generation
    except (Exception, asyncio.CancelledError) as error:
        request_id = (
            error.response.headers.get("x-request-id") if isinstance(error, APIResponseValidationError) else None
        )
        if gateway is not None and request_id:
            await _settle_generation(request_id, gateway=gateway, team_id=team_id, signal_id=signal_id, stage=stage)
        else:
            await database_sync_to_async(record_llm_spend)(
                None, token_cost_microusd=None, team_id=team_id, signal_id=signal_id, stage=stage
            )
        raise
    spend = await _settle_generation(
        getattr(response, "_request_id", None) if gateway is not None else None,
        gateway=gateway,
        team_id=team_id,
        signal_id=signal_id,
        stage=stage,
    )
    return PricedGeneration(response=response, spend=spend)
