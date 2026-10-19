from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization

from products.signals.backend.trial.billing import TrialBilling, TrialBillingStatus, TrialContinuation


class TestTrialBilling(SimpleTestCase):
    @parameterized.expand(
        [
            (False, False, 0, "0", 0, 0, 0, True, TrialContinuation.PAYMENT),
            (True, False, 0, "0", 50, 0, 0, True, TrialContinuation.ENABLE),
            (True, True, 0, "0.01", 0, 0, 0, True, TrialContinuation.LIMIT),
            (True, True, 0, "0.01", 50, 5000, 4999, True, TrialContinuation.PAID),
            (True, True, 0, "0.01", 50, 5000, 5000, True, TrialContinuation.LIMIT),
            (True, True, 0, "0.01", None, None, 9000, True, TrialContinuation.PAID),
            (False, False, 4500, "0", None, 4500, 0, False, TrialContinuation.PAYMENT),
            (True, True, 0, "0", 0, 4500, 0, False, TrialContinuation.LIMIT),
        ]
    )
    def test_existing_billing_status_determines_allowance_and_paid_continuation(
        self,
        has_subscription: bool,
        subscribed: bool,
        free_allocation: int,
        first_unit_price: str,
        spending_limit: int | None,
        usage_limit: int | None,
        current_usage: int,
        ready: bool,
        continuation: TrialContinuation,
    ) -> None:
        organization = Mock(spec=Organization)
        billing = {
            "has_active_subscription": has_subscription,
            "deactivated": False,
            "custom_limits_usd": {"inbox": spending_limit},
            "available_product_features": [
                {"key": "self_driving_trial_allowance_microusd", "limit": 10_000_000},
                {"key": "self_driving_trial_reports", "limit": 5},
            ],
            "products": [
                {
                    "type": "inbox",
                    "usage_key": "signals_credits",
                    "subscribed": subscribed,
                    "free_allocation": free_allocation,
                    "tiers": [{"unit_amount_usd": first_unit_price, "flat_amount_usd": "0"}] if subscribed else None,
                    "usage_limit": usage_limit,
                    "current_usage": current_usage,
                }
            ],
        }
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch("products.signals.backend.trial.billing.BillingManager.get_billing", return_value=billing),
        ):
            assert TrialBilling(organization).status() == TrialBillingStatus(ready=ready, continuation=continuation)

    @parameterized.expand(
        [
            (10_000_000, 5, True),
            (20_000_000, 10, True),
            (None, None, False, False),
            (None, None, False),
            (None, 5, False),
            (10_000_000, None, False),
            (0, 5, False),
            (10_000_000, 0, False),
            (-1, 5, False),
            (10_000_000, -1, False),
            (True, 5, False),
            (10_000_000, True, False),
            ("10000000", 5, False),
            (10_000_000, 5.5, False),
        ]
    )
    def test_finite_entitlements_gate_trial_without_blocking_paid_continuation(
        self, allowance: object, reports: object, ready: bool, include_features: bool = True
    ) -> None:
        product: dict[str, object] = {
            "type": "inbox",
            "usage_key": "signals_credits",
            "subscribed": True,
            "free_allocation": 0,
            "tiers": [{"unit_amount_usd": "0.01", "flat_amount_usd": "0"}],
            "usage_limit": None,
        }
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch(
                "products.signals.backend.trial.billing.BillingManager.get_billing",
                return_value={
                    "deactivated": False,
                    "has_active_subscription": True,
                    "products": [product],
                    "available_product_features": [
                        {"key": "self_driving_trial_allowance_microusd", "limit": allowance},
                        {"key": "self_driving_trial_reports", "limit": reports},
                    ]
                    if include_features
                    else [],
                },
            ),
        ):
            status = TrialBilling(Mock(spec=Organization)).status()
        assert status.ready is ready
        assert status.paid_authorized
        if ready:
            assert status.limits.allowance_microusd == allowance
            assert status.limits.report_limit == reports

    @parameterized.expand([({},), ({"deactivated": True},), ({"has_active_subscription": True, "products": []},)])
    def test_missing_billing_status_does_not_authorize_work(self, billing: dict[str, object]) -> None:
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch("products.signals.backend.trial.billing.BillingManager.get_billing", return_value=billing),
        ):
            status = TrialBilling(Mock(spec=Organization)).status()
        assert not status.ready
        assert not status.paid_authorized
