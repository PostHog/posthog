from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from requests.exceptions import ConnectTimeout, ReadTimeout

from posthog.models import Organization, Team

from products.signals.backend.trial.billing import (
    TrialBilling,
    TrialBillingStatus,
    TrialContinuation,
    paid_trial_continuation_authorized,
)

from ee.models import License


class TestTrialBilling(SimpleTestCase):
    @parameterized.expand(
        [
            (failure, licensed, billing_response)
            for failure in (ConnectTimeout, ReadTimeout)
            for licensed, billing_response in (
                (True, None),
                (False, None),
                (True, {"customer": None}),
                (True, {"customer": {"products": []}}),
                (True, {"customer": {"products": [], "customer_trust_scores": {"inbox_usage": 1}}}),
            )
        ]
    )
    def test_billing_timeouts_deny_paid_continuation(
        self, failure: type[Exception], licensed: bool, billing_response: dict[str, object] | None
    ) -> None:
        organization = Organization(name="Trial billing test", customer_id="cus_example", never_drop_data=None)
        team = Team(organization=organization)
        license = License(key="trial-test::synthetic-billing-secret-for-tests") if licensed else None
        responses: list[Mock | type[Exception]] = (
            [failure] if billing_response is None else [Mock(status_code=200, json=lambda: billing_response), failure]
        )
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=license),
            patch("ee.billing.billing_manager.get_cached_instance_license", return_value=license),
            patch("ee.billing.billing_manager.http_session.get", side_effect=responses) as get,
        ):
            assert not paid_trial_continuation_authorized(team)
        assert get.call_count == len(responses)
        assert all(call.kwargs["timeout"] == (3, 5) for call in get.call_args_list)

    @parameterized.expand(
        [
            (False, False, 0, "0", 0, 0, 0, True, TrialContinuation.PAYMENT),
            (False, None, 0, "0", 0, 0, 0, True, TrialContinuation.PAYMENT),
            (True, False, 0, "0", 50, 0, 0, True, TrialContinuation.ENABLE),
            (True, None, 0, "0", 50, 0, 0, True, TrialContinuation.ENABLE),
            (True, True, 0, "0.01", 0, 0, 0, True, TrialContinuation.LIMIT),
            (True, True, 0, "0.01", 50, 5000, 4999, True, TrialContinuation.PAID),
            (True, True, 0, "0.01", 50, 5000, 5000, True, TrialContinuation.LIMIT),
            (True, True, 0, "0.01", None, None, 9000, True, TrialContinuation.PAID),
            (False, False, 4500, "0", None, 4500, 0, False, TrialContinuation.PAYMENT),
            (True, True, 0, "0", 0, 4500, 0, False, TrialContinuation.LIMIT),
            (False, None, 0, "0", 0, 0, 0, False, TrialContinuation.UNAVAILABLE, False),
            (False, None, 0, "0", 0, 0, 0, False, TrialContinuation.UNAVAILABLE, None),
        ]
    )
    def test_existing_billing_status_determines_allowance_and_paid_continuation(
        self,
        has_subscription: bool,
        subscribed: bool | None,
        free_allocation: int,
        first_unit_price: str,
        spending_limit: int | None,
        usage_limit: int | None,
        current_usage: int,
        ready: bool,
        continuation: TrialContinuation,
        active: bool | None = True,
    ) -> None:
        organization = Organization(name="Trial billing test", is_active=active)
        billing = {
            "usage_summary": {"signals_spend_credits": {"billing_start_date": timezone.now().date().isoformat()}},
            "has_active_subscription": has_subscription,
            "custom_limits_usd": {"inbox_usage": spending_limit},
            "available_product_features": [
                {"key": "self_driving_trial_allowance_microusd", "limit": 10_000_000},
                {"key": "self_driving_trial_reports", "limit": 5},
            ],
            "products": [
                {
                    "type": "inbox_usage",
                    "usage_key": "signals_spend_credits",
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
            "type": "inbox_usage",
            "usage_key": "signals_spend_credits",
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
                    "usage_summary": {
                        "signals_spend_credits": {"billing_start_date": timezone.now().date().isoformat()}
                    },
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
            status = TrialBilling(Organization(name="Trial billing test")).status()
        assert status.ready is ready
        assert status.paid_authorized
        if ready:
            assert status.limits.allowance_microusd == allowance
            assert status.limits.report_limit == reports

    @parameterized.expand([({},), ({"has_active_subscription": True, "products": []},)])
    def test_missing_billing_status_does_not_authorize_work(self, billing: dict[str, object]) -> None:
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch("products.signals.backend.trial.billing.BillingManager.get_billing", return_value=billing),
        ):
            status = TrialBilling(Organization(name="Trial billing test")).status()
        assert not status.ready
        assert not status.paid_authorized
