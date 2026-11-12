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
        return _parsed_tiers(cached)
    try:
        billing = BillingManager(get_cached_instance_license())
        raw_tiers = _paid_plan_tiers(billing.get_default_products(None, timeout=_TIMEOUT_SECONDS)["products"])
    except Exception:
        # An estimate without prices still shows the rows, so a billing outage only drops the price.
        logger.exception("warehouse_migration_price_tiers_failed")
        return None
    tiers = _parsed_tiers(raw_tiers) if raw_tiers is not None else None
    if tiers is not None:
        # The billing service's JSON, not the parsed tiers, because the cache must hold only JSON-shaped values.
        cache.set(_CACHE_KEY, raw_tiers, _CACHE_SECONDS)
    return tiers


def _paid_plan_tiers(products: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    product = next((product for product in products if product.get("type") == _PRODUCT_TYPE), None)
    if product is None:
        return None
    # The free plan has no tiers. The paid plan's first tier is the free allowance.
    plan = next((plan for plan in product.get("plans") or [] if plan.get("tiers")), None)
    if plan is None:
        return None
    return [{key: tier.get(key) for key in ("up_to", "unit_amount_usd", "flat_amount_usd")} for tier in plan["tiers"]]


def _parsed_tiers(raw_tiers: list[dict[str, Any]]) -> tuple[PriceTier, ...] | None:
    try:
        return tuple(
            PriceTier(
                up_to=tier["up_to"],
                unit_amount_usd=Decimal(tier["unit_amount_usd"]),
                flat_amount_usd=Decimal(tier["flat_amount_usd"] or 0),
            )
            for tier in raw_tiers
        )
    except (KeyError, TypeError, InvalidOperation):
        logger.warning("warehouse_migration_price_tiers_unreadable")
        return None
