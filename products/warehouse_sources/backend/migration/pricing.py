"""PostHog's list price per warehouse row synced, read from the billing service."""

from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.cache import cache

import structlog

from posthog.cloud_utils import get_cached_instance_license

from products.warehouse_sources.backend.migration.cost import PriceTier

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)

_CACHE_KEY = "warehouse_migration_row_price_tiers"
_CACHE_SECONDS = 60 * 60
_TIMEOUT_SECONDS = (3.0, 5.0)
_PRODUCT_TYPE = "data_warehouse"


def row_price_tiers() -> tuple[PriceTier, ...] | None:
    """The standard plan's graduated tiers, free tier included. None when the billing service cannot be read."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        billing = BillingManager(get_cached_instance_license())
        tiers = _paid_tiers(billing.get_default_products(None, timeout=_TIMEOUT_SECONDS)["products"])
    except Exception:
        # An estimate without prices still shows the rows, so a billing outage only drops the price.
        logger.exception("warehouse_migration_price_tiers_failed")
        return None
    if tiers is not None:
        cache.set(_CACHE_KEY, tiers, _CACHE_SECONDS)
    return tiers


def _paid_tiers(products: list[dict[str, Any]]) -> tuple[PriceTier, ...] | None:
    product = next((product for product in products if product.get("type") == _PRODUCT_TYPE), None)
    if product is None:
        return None
    # The free plan has no tiers. The paid plan's first tier is the free allowance.
    plan = next((plan for plan in product.get("plans") or [] if plan.get("tiers")), None)
    if plan is None:
        return None
    try:
        return tuple(
            PriceTier(
                up_to=tier.get("up_to"),
                unit_amount_usd=Decimal(tier["unit_amount_usd"]),
                flat_amount_usd=Decimal(tier.get("flat_amount_usd") or 0),
            )
            for tier in plan["tiers"]
        )
    except (KeyError, TypeError, InvalidOperation):
        logger.warning("warehouse_migration_price_tiers_unreadable")
        return None
