import json
import asyncio
import inspect
from collections.abc import Awaitable
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from typing import Unpack
from uuid import uuid4

import httpx
import structlog
from anthropic import APIConnectionError, APIResponseValidationError, APIStatusError, AsyncAnthropic
from anthropic.types import Message
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost, fetch_gateway_cost
from posthog.sync import database_sync_to_async

from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.trial.llm_execution import TrialLLMExecution
from products.signals.backend.trial.policy import TrialRefused

logger = structlog.get_logger(__name__)
USAGE_WAIT_SECONDS = 10.0
_generation_source: ContextVar[str | None] = ContextVar("signals_generation_source", default=None)


class AccountedMessageParams(MessageCreateParamsNonStreaming, total=False):
    extra_headers: dict[str, str]
    timeout: float


async def accounted_message(client: AsyncAnthropic, **kwargs: Unpack[AccountedMessageParams]) -> Message:
    source_id = _generation_source.get()
    if source_id:
        headers = dict(kwargs.pop("extra_headers", {}) or {})
        properties = json.loads(
            headers.get("X-PostHog-Properties") or client.default_headers.get("X-PostHog-Properties") or "{}"
        )
        properties["signals_cost_source_id"] = source_id
        headers["X-PostHog-Properties"] = json.dumps(properties)
        kwargs["extra_headers"] = headers
        client = client.with_options(max_retries=0)
    return await client.messages.create(**kwargs)


@frozen
class PricedGeneration:
    response: Message
    spend: Decimal | None


def _usage_wait_seconds() -> float:
    budget = USAGE_WAIT_SECONDS
    if activity.in_activity():
        info = activity.info()
        now = datetime.now(UTC)
        for started, timeout in (
            (info.started_time, info.start_to_close_timeout),
            (info.scheduled_time, info.schedule_to_close_timeout),
        ):
            if timeout is not None:
                budget = min(budget, (started + timeout - now).total_seconds() - 1)
    return max(0, budget)


async def _wait_for_gateway_cost(request_id: str, gateway: AIGatewayConfig) -> GatewayRequestCost:
    delay = 0.01
    while True:
        cost = await fetch_gateway_cost(request_id, base_url=gateway.url, api_key=gateway.api_key)
        if cost is not None:
            return cost
        if activity.in_activity():
            activity.heartbeat()
        await asyncio.sleep(delay)
        delay = min(delay * 2, 1.0)


async def _settle_generation(
    request_id: str | None,
    *,
    gateway: AIGatewayConfig | None,
    team_id: int | None,
    signal_id: str | None,
    stage: str,
    source_id: str | None = None,
    trial_grant_id: str | None = None,
) -> Decimal | None:
    cost_microusd = None
    try:
        if gateway is None or not request_id or team_id is None or signal_id is None:
            return None
        cost = await asyncio.wait_for(_wait_for_gateway_cost(request_id, gateway), timeout=_usage_wait_seconds())
        cost_microusd = cost.cost_microusd
        return cost_to_spend(cost_microusd)
    except TimeoutError:
        logger.warning("signals.spend.usage_wait_expired", stage=stage, team_id=team_id, signal_id=signal_id)
        return None
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
            source_id=source_id,
            trial_grant_id=trial_grant_id,
        )


async def generate_with_spend(
    generation: Awaitable[Message],
    *,
    gateway: AIGatewayConfig | None,
    team_id: int | None,
    signal_id: str | None,
    stage: str,
) -> PricedGeneration:
    trial = None
    token = None
    try:
        trial = await database_sync_to_async(TrialLLMExecution.prepare)(team_id=team_id, gateway=gateway)
        source_id = f"generation:{uuid4()}" if trial else None
        trial_grant_id = str(trial.operation.grant_id) if trial else None
        signal_id = signal_id or (str(trial.operation.id) if trial else None)
        if trial:
            token = _generation_source.set(source_id)
            await database_sync_to_async(record_llm_spend)(
                None,
                token_cost_microusd=None,
                team_id=team_id,
                signal_id=signal_id,
                stage=stage,
                source_id=source_id,
                trial_grant_id=trial_grant_id,
            )
        return await _generate_with_spend(
            generation,
            gateway=gateway,
            team_id=team_id,
            signal_id=signal_id,
            stage=stage,
            source_id=source_id,
            trial_grant_id=trial_grant_id,
        )
    finally:
        if token is not None:
            _generation_source.reset(token)
        if inspect.iscoroutine(generation):
            generation.close()
        if trial:
            await database_sync_to_async(trial.finish)()


async def _generate_with_spend(
    generation: Awaitable[Message],
    *,
    gateway: AIGatewayConfig | None,
    team_id: int | None,
    signal_id: str | None,
    stage: str,
    source_id: str | None,
    trial_grant_id: str | None,
) -> PricedGeneration:
    """Generate once, then wait for its gateway usage. Spend is in USD cents.

    Accounting waits up to ten seconds within the calling activity, leaving time
    to return before its deadline. Missing usage preserves the completed response
    and marks the stage unaccounted.
    """
    try:
        response = await generation
    except (Exception, asyncio.CancelledError) as error:
        request_id = (
            error.response.headers.get("x-request-id") or error.response.headers.get("request-id")
            if isinstance(error, (APIResponseValidationError, APIStatusError))
            else None
        )
        if gateway is not None and request_id:
            await _settle_generation(
                request_id,
                gateway=gateway,
                team_id=team_id,
                signal_id=signal_id,
                stage=stage,
                source_id=source_id,
                trial_grant_id=trial_grant_id,
            )
        else:
            await database_sync_to_async(record_llm_spend)(
                None,
                token_cost_microusd=0
                if isinstance(error, TrialRefused)
                or (
                    isinstance(error, APIConnectionError)
                    and isinstance(error.__cause__, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                )
                else None,
                team_id=team_id,
                signal_id=signal_id,
                stage=stage,
                source_id=source_id,
                trial_grant_id=trial_grant_id,
            )
        raise
    spend = await _settle_generation(
        getattr(response, "_request_id", None) if gateway is not None else None,
        gateway=gateway,
        team_id=team_id,
        signal_id=signal_id,
        stage=stage,
        source_id=source_id,
        trial_grant_id=trial_grant_id,
    )
    return PricedGeneration(response=response, spend=spend)
