from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

logger = structlog.get_logger(__name__)

_CACHE_KEY_PREFIX = "tasks:llm_gateway_models:v2"
_LAST_GOOD_CACHE_KEY_PREFIX = "tasks:llm_gateway_models:last_good"
_CACHE_TTL_SECONDS = 30 * 60
_NEGATIVE_CACHE_TTL_SECONDS = 30
_LAST_GOOD_TTL_SECONDS = 6 * 60 * 60
_FETCH_TIMEOUT_SECONDS = 3.0
_TOKENS_PER_MTOK = 1_000_000


@frozen
class GatewayModel:
    id: str
    owned_by: str
    context_window: int
    name: str = ""
    family: str = ""
    release_date: str = ""
    reasoning_efforts: tuple[str, ...] | None = None
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None


def _text(row: Any, field: str) -> str:
    value = getattr(row, field, None)
    return value if isinstance(value, str) else ""


def _reasoning_efforts(row: Any) -> tuple[str, ...] | None:
    reasoning = getattr(row, "reasoning", None)
    efforts = reasoning.get("efforts") if isinstance(reasoning, dict) else None
    if not isinstance(efforts, list):
        return None
    return tuple(effort for effort in efforts if isinstance(effort, str))


def _per_mtok(row: Any, field: str) -> float | None:
    pricing = getattr(row, "pricing", None)
    per_token = pricing.get(field) if isinstance(pricing, dict) else None
    if not isinstance(per_token, str | int | float) or isinstance(per_token, bool):
        return None
    try:
        return float(Decimal(str(per_token)) * _TOKENS_PER_MTOK)
    except InvalidOperation:
        return None


def _gateway_model(row: Any) -> GatewayModel:
    context_window = getattr(row, "context_window", 0)
    return GatewayModel(
        id=row.id,
        owned_by=_text(row, "owned_by"),
        context_window=context_window if isinstance(context_window, int) else 0,
        name=_text(row, "name"),
        family=_text(row, "family"),
        release_date=_text(row, "release_date"),
        reasoning_efforts=_reasoning_efforts(row),
        input_per_mtok=_per_mtok(row, "prompt"),
        output_per_mtok=_per_mtok(row, "completion"),
    )


def _cache_quietly(key: str, value: tuple[GatewayModel, ...], timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.exception("tasks_llm_gateway_models_cache_write_failed", cache_key=key)


def _last_good(product: Product) -> tuple[GatewayModel, ...]:
    try:
        return cache.get(f"{_LAST_GOOD_CACHE_KEY_PREFIX}:{product}") or ()
    except Exception:
        return ()


def list_gateway_models(product: Product) -> tuple[GatewayModel, ...]:
    cache_key = f"{_CACHE_KEY_PREFIX}:{product}"

    from posthog.llm.gateway_client import build_openai_client  # noqa: PLC0415 — keeps the LLM SDKs off startup paths

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        client = build_openai_client(product, ai_product=product)
        page = client.with_options(timeout=_FETCH_TIMEOUT_SECONDS, max_retries=0).models.list()
        models = tuple(_gateway_model(row) for row in page.data if getattr(row, "allowed", None) is not False)
    except Exception:
        logger.exception("tasks_llm_gateway_models_fetch_failed", gateway_product=product)
        fallback = _last_good(product)
        _cache_quietly(cache_key, fallback, _NEGATIVE_CACHE_TTL_SECONDS)
        return fallback

    _cache_quietly(cache_key, models, _CACHE_TTL_SECONDS)
    if models:
        _cache_quietly(f"{_LAST_GOOD_CACHE_KEY_PREFIX}:{product}", models, _LAST_GOOD_TTL_SECONDS)
    return models
