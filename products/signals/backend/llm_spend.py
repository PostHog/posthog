import asyncio
from collections.abc import Awaitable
from decimal import Decimal
from json import JSONDecodeError

from anthropic import APIResponseValidationError
from anthropic.types import Message
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import fetch_gateway_cost
from posthog.sync import database_sync_to_async

from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend import record_llm_spend


@frozen
class PricedGeneration:
    response: Message
    spend: Decimal


async def _settle_generation(
    request_id: str | None,
    *,
    gateway: AIGatewayConfig,
    team_id: int,
    signal_id: str,
    stage: str,
) -> Decimal:
    cost_microusd = None
    try:
        if not request_id:
            raise ValueError("Gateway generation has no request ID for spend accounting")
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
    gateway: AIGatewayConfig,
    team_id: int,
    signal_id: str,
    stage: str,
) -> PricedGeneration:
    """Generate once, then wait for its gateway usage. Spend is in USD cents.

    Polling stays in the calling activity and is cancellable by its lifetime; an
    unavailable usage record never causes another generation or a zero estimate.
    """
    try:
        response = await generation
    except (APIResponseValidationError, JSONDecodeError) as error:
        request_id = (
            error.response.headers.get("x-request-id") if isinstance(error, APIResponseValidationError) else None
        )
        if request_id:
            await _settle_generation(request_id, gateway=gateway, team_id=team_id, signal_id=signal_id, stage=stage)
        else:
            await database_sync_to_async(record_llm_spend)(
                None, token_cost_microusd=None, team_id=team_id, signal_id=signal_id, stage=stage
            )
        raise
    spend = await _settle_generation(
        getattr(response, "_request_id", None), gateway=gateway, team_id=team_id, signal_id=signal_id, stage=stage
    )
    return PricedGeneration(response=response, spend=spend)
