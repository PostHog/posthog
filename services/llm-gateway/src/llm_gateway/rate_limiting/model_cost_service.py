from __future__ import annotations

import time
from typing import Final, TypedDict, cast

import litellm
import structlog
from litellm import model_cost_map_url
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

logger = structlog.get_logger(__name__)

TARGET_LIMIT_COST_PER_HOUR: Final[float] = 20.0
CACHE_TTL_SECONDS: Final[int] = 300


class ModelLimits(TypedDict):
    """Rate limits for a model based on cost."""

    input_tph: int
    """Maximum input tokens per hour."""
    output_tph: int
    """Maximum output tokens per hour."""


DEFAULT_LIMITS: Final[ModelLimits] = {"input_tph": 2_000_000, "output_tph": 400_000}


class ModelCost(TypedDict, total=False):
    """Model cost and capability information from litellm."""

    input_cost_per_token: float
    """Cost in USD per input token."""
    output_cost_per_token: float
    """Cost in USD per output token."""
    max_input_tokens: int
    """Maximum input context length in tokens."""
    max_output_tokens: int
    """Maximum output tokens the model can generate."""
    max_tokens: int
    """Legacy field: defaults to max_output_tokens if set, otherwise max_input_tokens."""
    litellm_provider: str
    """Provider identifier (e.g., "anthropic", "openai", "vertex_ai")."""


class ModelCostService:
    """Singleton service for model costs and rate limits with caching."""

    _instance: ModelCostService | None = None

    def __init__(self) -> None:
        self._costs: dict[str, ModelCost] = {}
        self._limits: dict[str, ModelLimits] = {}
        self._last_refresh: float = 0

    @classmethod
    def get_instance(cls) -> ModelCostService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def _should_refresh(self) -> bool:
        return time.monotonic() - self._last_refresh > CACHE_TTL_SECONDS

    def _refresh_cache(self) -> None:
        try:
            model_cost = get_model_cost_map(url=model_cost_map_url)
            litellm.model_cost = model_cost
            self._costs = cast(dict[str, ModelCost], model_cost)
            new_limits: dict[str, ModelLimits] = {}
            for model, cost in self._costs.items():
                input_cost = cost.get("input_cost_per_token")
                output_cost = cost.get("output_cost_per_token")
                if input_cost and output_cost and input_cost > 0 and output_cost > 0:
                    new_limits[model] = {
                        "input_tph": int(TARGET_LIMIT_COST_PER_HOUR / input_cost),
                        "output_tph": int(TARGET_LIMIT_COST_PER_HOUR / output_cost),
                    }
            self._limits = new_limits
            self._last_refresh = time.monotonic()
            logger.info("model_cost_cache_refreshed", model_count=len(new_limits))
        except Exception:
            logger.exception("model_cost_cache_refresh_failed")

    def _ensure_fresh(self) -> None:
        if self._should_refresh():
            self._refresh_cache()

    def get_limits(self, model: str) -> ModelLimits:
        self._ensure_fresh()
        limits = self._limits.get(model)
        if limits is None:
            logger.warning("model_not_found_in_cost_map", model=model)
            return DEFAULT_LIMITS
        return limits

    def get_costs(self, model: str) -> ModelCost | None:
        self._ensure_fresh()
        return self._costs.get(model)


def get_model_limits(model: str) -> ModelLimits:
    return ModelCostService.get_instance().get_limits(model)


def get_model_costs(model: str) -> ModelCost | None:
    return ModelCostService.get_instance().get_costs(model)
