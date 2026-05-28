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
COST_ALIASES: dict[str, str] = {
    "openai/@cf/moonshotai/kimi-k2.6": "moonshot/kimi-k2.6",
}


def apply_cost_aliases(model_cost: dict[str, Any]) -> None:
    """Mutate model_cost to add alias keys for non-canonical provider routings.

    Every writer to `litellm.model_cost` must call this — otherwise alias-routed
    models fall back to default cost in the rate-limiting callback. A missing
    canonical is logged so cost map regressions surface in alerting instead of
    silently routing requests through the default fallback cost.
    """
    for alias, canonical in COST_ALIASES.items():
        if alias in model_cost:
            continue
        if canonical in model_cost:
            model_cost[alias] = model_cost[canonical]
        else:
            logger.warning("cost_alias_canonical_missing", alias=alias, canonical=canonical)


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
            apply_cost_aliases(model_cost)
            litellm.model_cost = model_cost
            self._last_refresh = time.monotonic()
            logger.info("model_cost_refreshed", model_count=len(model_cost))
        except Exception:
            logger.exception("model_cost_refresh_failed")

    def ensure_fresh(self) -> None:
        if self._should_refresh():
            self.refresh()


def ensure_costs_fresh() -> None:
    CostRefreshService.get_instance().ensure_fresh()
