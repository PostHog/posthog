from __future__ import annotations

import time
from typing import Any

import litellm
import structlog
from litellm import model_cost_map_url
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 300

# Models routed through non-canonical litellm providers (e.g. Cloudflare via
# openai/ prefix) won't match their cost map entry. Map the key we actually
# pass to litellm → the canonical key in the cost map.
#
# Note on Cloudflare entries: litellm doesn't publish per-model CF prices for
# anything beyond a few legacy Llama-2/Mistral variants. We alias to the model
# vendor's direct rate (e.g. moonshot/kimi-k2.6) as a proxy; this is *not* CF's
# actual resold rate, and may drift if CF introduces markup or flat-rate billing.
COST_ALIASES: dict[str, str] = {
    "openai/@cf/moonshotai/kimi-k2.6": "moonshot/kimi-k2.6",
}

# For the same aliased models, the (provider, model) labels litellm reports
# don't match what the user asked for. Map the litellm-view model key → the
# user-facing (provider, model) pair we want to emit in metrics. Kept separate
# from COST_ALIASES because cost lookups go through litellm.model_cost (keyed
# on the litellm-view model), while metric labels should reflect user intent.
ALIAS_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "openai/@cf/moonshotai/kimi-k2.6": ("cloudflare", "@cf/moonshotai/kimi-k2.6"),
}


def normalize_metric_labels(litellm_model: str, litellm_provider: str) -> tuple[str, str]:
    """Translate the (provider, model) labels litellm sees into the user-facing
    (provider, model) we want in metrics. Returns (provider, model).
    """
    override = ALIAS_METRIC_LABELS.get(litellm_model)
    if override is None:
        return litellm_provider, litellm_model
    return override


def apply_cost_aliases(model_cost: dict[str, Any]) -> None:
    """Add alias keys for non-canonical provider routings. Prefer `set_litellm_model_cost`."""
    for alias, canonical in COST_ALIASES.items():
        if alias in model_cost:
            continue
        if canonical in model_cost:
            # Shallow copy so a future in-place mutation under one key doesn't bleed into the other.
            model_cost[alias] = dict(model_cost[canonical])
        else:
            logger.warning("cost_alias_canonical_missing", alias=alias, canonical=canonical)


def set_litellm_model_cost(model_cost: dict[str, Any]) -> None:
    """Single writer for `litellm.model_cost` — applies aliases atomically."""
    apply_cost_aliases(model_cost)
    litellm.model_cost = model_cost


class CostRefreshService:
    """Singleton service that periodically refreshes litellm.model_cost."""

    _instance: CostRefreshService | None = None

    def __init__(self) -> None:
        self._last_refresh: float = 0

    @classmethod
    def get_instance(cls) -> CostRefreshService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def _should_refresh(self) -> bool:
        if self._last_refresh == 0:
            return True
        return time.monotonic() - self._last_refresh > CACHE_TTL_SECONDS

    def refresh(self) -> None:
        try:
            model_cost = get_model_cost_map(url=model_cost_map_url)
            set_litellm_model_cost(model_cost)
            self._last_refresh = time.monotonic()
            logger.info("model_cost_refreshed", model_count=len(model_cost))
        except Exception:
            logger.exception("model_cost_refresh_failed")

    def ensure_fresh(self) -> None:
        if self._should_refresh():
            self.refresh()


def ensure_costs_fresh() -> None:
    CostRefreshService.get_instance().ensure_fresh()
