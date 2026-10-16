from decimal import Decimal
from typing import cast

from django.db import models

import structlog

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import CustomerInfo, CustomerProduct
from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


class TrialContinuation(models.TextChoices):
    PAID = "continue_paid", "Continue under existing paid authorization"
    PAYMENT = "add_payment_method", "Add a payment method"
    LIMIT = "increase_limit", "Increase the Self-driving spending limit"
    ENABLE = "enable_self_driving", "Enable paid Self-driving"
    UNAVAILABLE = "unavailable", "Billing status unavailable"


@frozen
class TrialBillingStatus:
    ready: bool
    continuation: TrialContinuation

    @property
    def paid_authorized(self) -> bool:
        return self.continuation == TrialContinuation.PAID


class TrialBilling:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    @staticmethod
    def _has_zero_allowance(product: CustomerProduct) -> bool:
        if product.get("free_allocation") != 0:
            return False
        if product.get("subscribed") is False:
            return True
        # Paid plans carry their free allowance in the price tiers, not free_allocation.
        tiers = product.get("tiers")
        if not tiers:
            return False
        first = tiers[0]
        unit_price = Decimal(first["unit_amount_usd"])
        flat_price = Decimal(first["flat_amount_usd"])
        return unit_price.is_finite() and flat_price.is_finite() and (unit_price > 0 or flat_price > 0)

    def status(self) -> TrialBillingStatus:
        customer = cast(
            CustomerInfo,
            BillingManager(get_cached_instance_license()).get_billing(
                self.organization, query_params={"include_forecasting": "false"}
            ),
        )
        product = next((p for p in customer.get("products") or [] if p.get("type") == "inbox"), None)
        if (
            customer.get("deactivated") is not False
            or type(customer.get("has_active_subscription")) is not bool
            or product is None
            or product.get("usage_key") != "signals_credits"
            or type(product.get("subscribed")) is not bool
            or "usage_limit" not in product
        ):
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        limit = product["usage_limit"]
        if not customer["has_active_subscription"]:
            continuation = TrialContinuation.PAYMENT
        elif not product["subscribed"]:
            continuation = TrialContinuation.ENABLE
        elif (customer.get("custom_limits_usd") or {}).get("inbox") == 0 or (
            limit is not None and product["current_usage"] >= limit
        ):
            continuation = TrialContinuation.LIMIT
        else:
            continuation = TrialContinuation.PAID
        return TrialBillingStatus(ready=self._has_zero_allowance(product), continuation=continuation)


def paid_trial_continuation_authorized(team: Team) -> bool:
    try:
        return TrialBilling(team.organization).status().paid_authorized and not is_team_limited(
            team.api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_trial_paid_authorization_unavailable", team_id=team.id, exc_info=True)
        return False
