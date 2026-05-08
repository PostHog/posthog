from __future__ import annotations

import asyncio

import structlog

from llm_gateway.config import get_settings
from llm_gateway.metrics.prometheus import (
    PRODUCT_COST_LIMIT_USD,
    PRODUCT_COST_WINDOW_SECONDS,
    PRODUCT_COST_WINDOW_USD,
)
from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 30


async def _publish_once(throttle: ProductCostThrottle) -> None:
    products = list(get_settings().product_cost_limits.keys())
    for product in products:
        try:
            status = await throttle.get_status_for_product(product)
            if status is None:
                continue
            PRODUCT_COST_WINDOW_USD.labels(product=product).set(status.used_usd)
            PRODUCT_COST_LIMIT_USD.labels(product=product).set(status.limit_usd)
            PRODUCT_COST_WINDOW_SECONDS.labels(product=product).set(status.resets_in_seconds)
        except Exception:
            logger.exception("product_cost_gauge_publish_failed", product=product)


async def publish_product_cost_gauges_loop(
    throttle: ProductCostThrottle,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Periodically read each product's shared-pool spend from Redis and publish
    it as Prometheus gauges, so alerting can compare current spend to the cap
    without tying freshness to request traffic.
    """
    logger.info("product_cost_gauge_publisher_started", interval_seconds=interval_seconds)

    while True:
        try:
            await _publish_once(throttle)
        except asyncio.CancelledError:
            logger.info("product_cost_gauge_publisher_stopped")
            raise
        except Exception:
            logger.exception("product_cost_gauge_publish_loop_failed")

        await asyncio.sleep(interval_seconds)
