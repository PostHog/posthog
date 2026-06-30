"""Slack-app view of the models the LLM gateway exposes for `slack_app`.

The gateway is the source of truth — hardcoding the list here would mean a
Slack-side PR every time it changes. Cached via Django's shared cache so the
Home tab publish never blocks on a gateway round-trip; the fetch timeout is
capped at 3s because it sits on the Slack interactivity hot path (trigger_id
expires after ~3s), and failures are negatively cached for 30s so a broken
gateway can't make every interaction wait the full timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

import structlog

from posthog.llm.gateway_client import get_llm_client

logger = structlog.get_logger(__name__)

_CACHE_KEY = "slack_app:llm_gateway_models"
_CACHE_TTL_SECONDS = 30 * 60
_NEGATIVE_CACHE_TTL_SECONDS = 30
_FETCH_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class GatewayModel:
    id: str
    owned_by: str
    context_window: int


def list_slack_app_models() -> tuple[GatewayModel, ...]:
    """Return the model list the `slack_app` gateway product exposes.

    Returns an empty tuple on any error. The empty result is briefly cached
    so subsequent interactions during an outage fail fast.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        page = get_llm_client(product="slack_app").with_options(timeout=_FETCH_TIMEOUT_SECONDS).models.list()
    except Exception:
        logger.exception("slack_app_llm_gateway_models_fetch_failed")
        cache.set(_CACHE_KEY, (), timeout=_NEGATIVE_CACHE_TTL_SECONDS)
        return ()

    models = tuple(
        GatewayModel(
            id=m.id,
            owned_by=getattr(m, "owned_by", ""),
            context_window=getattr(m, "context_window", 0),
        )
        for m in page.data
    )
    cache.set(_CACHE_KEY, models, timeout=_CACHE_TTL_SECONDS)
    return models
