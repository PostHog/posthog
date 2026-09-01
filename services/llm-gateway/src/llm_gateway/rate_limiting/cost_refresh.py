from __future__ import annotations

import time
from typing import Any

import litellm
import structlog
from litellm import model_cost_map_url
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

from llm_gateway.baseten import (
    BASETEN_DEEPSEEK_METRIC_MODEL,
    BASETEN_DEEPSEEK_MODEL,
    BASETEN_GLM53_FLASH_METRIC_MODEL,
    BASETEN_GLM53_FLASH_MODEL,
    BASETEN_GLM53_METRIC_MODEL,
    BASETEN_GLM53_MODEL,
    BASETEN_METRIC_MODEL,
)
from llm_gateway.rate_limiting.model_cost_overrides import apply_model_cost_overrides

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 300

# Models on non-canonical litellm providers (e.g. Cloudflare via openai/ prefix) don't match their
# cost map entry. Map the key we pass to litellm → the canonical cost-map key.
#
# CF entries: alias to litellm's native `cloudflare/@cf/...` price where it carries one (CF's actual
# resold rate). For models litellm only prices under the vendor's own key, alias to that direct rate
# as a proxy — not CF's resold rate, and may drift if CF adds markup or flat-rate billing.
COST_ALIASES: dict[str, tuple[str, str]] = {
    "openai/@cf/moonshotai/kimi-k2.6": ("moonshot/kimi-k2.6", "openai"),
    "openai/@cf/zai-org/glm-5.2": ("cloudflare/@cf/zai-org/glm-5.2", "openai"),
    # Modal serves the same GLM checkpoint; billed at the CF rate until trued
    # up against Modal's GPU-time invoices.
    "openai/zai-org/GLM-5.2-FP8": ("cloudflare/@cf/zai-org/glm-5.2", "openai"),
    "openai/zai-org/GLM-5.2": (BASETEN_METRIC_MODEL, "openai"),
    f"openai/{BASETEN_DEEPSEEK_MODEL}": (BASETEN_DEEPSEEK_METRIC_MODEL, "openai"),
    f"openai/{BASETEN_GLM53_MODEL}": (BASETEN_GLM53_METRIC_MODEL, "openai"),
    f"openai/{BASETEN_GLM53_FLASH_MODEL}": (BASETEN_GLM53_FLASH_METRIC_MODEL, "openai"),
    "openai/moonshotai/kimi-k3": ("moonshotai/kimi-k3", "openai"),
}

# Map LiteLLM's provider and model labels to stable telemetry identifiers. This stays separate from
# COST_ALIASES because cost lookups and telemetry have different canonical names.
ALIAS_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "openai/@cf/moonshotai/kimi-k2.6": ("cloudflare", "@cf/moonshotai/kimi-k2.6"),
    "openai/@cf/zai-org/glm-5.2": ("cloudflare", "@cf/zai-org/glm-5.2"),
    # Same public model id as the CF entry so dashboards slice one model across both backends.
    "openai/zai-org/GLM-5.2-FP8": ("modal", "@cf/zai-org/glm-5.2"),
    "openai/zai-org/GLM-5.2": ("baseten", BASETEN_METRIC_MODEL),
    f"openai/{BASETEN_DEEPSEEK_MODEL}": ("baseten", BASETEN_DEEPSEEK_METRIC_MODEL),
    f"openai/{BASETEN_GLM53_MODEL}": ("baseten", BASETEN_GLM53_METRIC_MODEL),
    f"openai/{BASETEN_GLM53_FLASH_MODEL}": ("baseten", BASETEN_GLM53_FLASH_METRIC_MODEL),
    "openai/moonshotai/kimi-k3": ("modal", "moonshotai/kimi-k3"),
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
    for alias, (canonical, provider) in COST_ALIASES.items():
        if alias in model_cost:
            continue
        if canonical in model_cost:
            model_cost[alias] = {**model_cost[canonical], "litellm_provider": provider}
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
            apply_model_cost_overrides(model_cost)
            set_litellm_model_cost(model_cost)
            # Re-register provider sets (anthropic_models, etc.); else they stay frozen at import time.
            litellm.add_known_models(model_cost)
            self._last_refresh = time.monotonic()
            logger.info("model_cost_refreshed", model_count=len(model_cost))
        except Exception:
            logger.exception("model_cost_refresh_failed")

    def ensure_fresh(self) -> None:
        if self._should_refresh():
            self.refresh()


def ensure_costs_fresh() -> None:
    CostRefreshService.get_instance().ensure_fresh()
