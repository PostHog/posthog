from datetime import date
from decimal import Decimal
from typing import cast

from django.db import models
from django.utils import timezone

import structlog

from posthog.cloud_utils import get_cached_instance_license
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import CustomerInfo, CustomerProduct
from ee.billing.quota_limiting import QuotaLimitingCaches, is_team_limited, self_driving_quota_resource

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
    limits: TrialLimits = STANDARD_TRIAL_LIMITS

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
        if product.get("subscribed") is not True:
            return True
        # Paid plans carry their free allowance in the price tiers, not free_allocation.
        tiers = product.get("tiers")
        if not tiers:
            return False
        first = tiers[0]
        unit_price = Decimal(first["unit_amount_usd"])
        flat_price = Decimal(first["flat_amount_usd"])
        return unit_price.is_finite() and flat_price.is_finite() and (unit_price > 0 or flat_price > 0)

    @staticmethod
    def _trial_limits(customer: CustomerInfo) -> TrialLimits | None:
        features = {
            feature["key"]: feature.get("limit") for feature in customer.get("available_product_features") or []
        }
        allowance = features.get(AvailableFeature.SELF_DRIVING_TRIAL_ALLOWANCE_MICROUSD)
        reports = features.get(AvailableFeature.SELF_DRIVING_TRIAL_REPORTS)
        if allowance is None or reports is None:
            return None
        try:
            return TrialLimits(allowance_microusd=allowance, report_limit=reports)
        except ValueError:
            return None

    def status(self) -> TrialBillingStatus:
        if self.organization.is_active is not True:
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        customer = cast(
            CustomerInfo,
            BillingManager(get_cached_instance_license()).get_billing(
                self.organization, query_params={"include_forecasting": "false"}, timeout=(3, 5)
            ),
        )
        summaries = customer.get("usage_summary")
        spend_summary = summaries.get("signals_spend_credits") if summaries else None
        cutoff = spend_summary.get("billing_start_date") if spend_summary else None
        if not isinstance(cutoff, str):
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        try:
            enrolled = (
                date.fromisoformat(cutoff).isoformat() == cutoff and date.fromisoformat(cutoff) <= timezone.now().date()
            )
        except ValueError:
            enrolled = False
        if not enrolled:
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        product = next((p for p in customer.get("products") or [] if p.get("type") == "inbox_usage"), None)
        if (
            type(customer.get("has_active_subscription")) is not bool
            or product is None
            or product.get("usage_key") != "signals_spend_credits"
            or "subscribed" not in product
            or (product["subscribed"] is not None and type(product["subscribed"]) is not bool)
            or "usage_limit" not in product
        ):
            return TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE)
        limit = product["usage_limit"]
        if not customer["has_active_subscription"]:
            continuation = TrialContinuation.PAYMENT
        elif not product["subscribed"]:
            continuation = TrialContinuation.ENABLE
        elif (customer.get("custom_limits_usd") or {}).get("inbox_usage") == 0 or (
            limit is not None and product["current_usage"] >= limit
        ):
            continuation = TrialContinuation.LIMIT
        else:
            continuation = TrialContinuation.PAID
        limits = self._trial_limits(customer)
        if limits is None:
            return TrialBillingStatus(ready=False, continuation=continuation)
        return TrialBillingStatus(
            ready=self._has_zero_allowance(product),
            continuation=continuation,
            limits=limits,
        )


def paid_trial_continuation_authorized(team: Team) -> bool:
    try:
        return TrialBilling(team.organization).status().paid_authorized and not is_team_limited(
            team.api_token, self_driving_quota_resource(team.organization), QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_trial_paid_authorization_unavailable", team_id=team.id, exc_info=True)
        return False
