from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from llm_gateway.config import get_settings
from llm_gateway.metrics.prometheus import (
    PRODUCT_COST_LIMIT_USD,
    PRODUCT_COST_WINDOW_SECONDS,
    PRODUCT_COST_WINDOW_USD,
)
from llm_gateway.rate_limiting.cost_gauge_publisher import _publish_once
from llm_gateway.rate_limiting.cost_throttles import CostStatus, ProductCostThrottle


@pytest.mark.asyncio
async def test_publish_once_sets_gauges_for_each_product() -> None:
    get_settings.cache_clear()
    throttle = ProductCostThrottle(redis=None)
    throttle.get_status_for_product = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda product: CostStatus(
            used_usd=100.0,
            limit_usd=1000.0,
            remaining_usd=900.0,
            resets_in_seconds=3600,
            exceeded=False,
        )
    )

    await _publish_once(throttle)

    for product in get_settings().product_cost_limits:
        assert PRODUCT_COST_WINDOW_USD.labels(product=product)._value.get() == 100.0
        assert PRODUCT_COST_LIMIT_USD.labels(product=product)._value.get() == 1000.0
        assert PRODUCT_COST_WINDOW_SECONDS.labels(product=product)._value.get() == 3600
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_publish_once_skips_failing_product_and_continues() -> None:
    get_settings.cache_clear()
    throttle = ProductCostThrottle(redis=None)
    products = list(get_settings().product_cost_limits.keys())
    assert len(products) >= 2, "test needs at least two configured products"
    failing_product, healthy_product = products[0], products[1]

    async def fake_status(product: str) -> CostStatus | None:
        if product == failing_product:
            raise RuntimeError("redis boom")
        return CostStatus(
            used_usd=7.0,
            limit_usd=1000.0,
            remaining_usd=993.0,
            resets_in_seconds=60,
            exceeded=False,
        )

    throttle.get_status_for_product = AsyncMock(side_effect=fake_status)  # type: ignore[method-assign]

    PRODUCT_COST_WINDOW_USD.labels(product=healthy_product).set(0.0)

    await _publish_once(throttle)

    assert PRODUCT_COST_WINDOW_USD.labels(product=healthy_product)._value.get() == 7.0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_publish_once_skips_product_with_no_config() -> None:
    get_settings.cache_clear()
    throttle = ProductCostThrottle(redis=None)
    throttle.get_status_for_product = AsyncMock(return_value=None)  # type: ignore[method-assign]

    await _publish_once(throttle)
    get_settings.cache_clear()
