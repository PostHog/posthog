from __future__ import annotations

import time

import litellm
import structlog
from litellm import model_cost_map_url
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 300


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
