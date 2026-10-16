from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team

from products.signals.backend.trial.billing import TrialBilling, TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialOrganization


class TestTrialAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.url = f"/api/projects/{self.team.pk}/signals/trial/"
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)

    @parameterized.expand([(TrialContinuation.PAYMENT,), (TrialContinuation.LIMIT,), (TrialContinuation.PAID,)])
    def test_all_cohorts_can_explicitly_claim_once(self, continuation: TrialContinuation) -> None:
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=continuation),
        ):
            status = self.client.get(self.url)
            assert status.status_code == 200
            assert status.json()["eligible"]
            assert status.json()["legacy_pr_restricted"]
            assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
            first = self.client.post(self.url, {}, format="json")
            second = self.client.post(self.url, {}, format="json")
        assert first.status_code == 200, first.content
        assert first.json()["grant_id"] == second.json()["grant_id"]
        assert first.json()["paid_continuation"] == continuation
        assert first.json()["legacy_pr_restricted"] is False
        assert SignalTrialOrganization.objects.get(organization_id=self.organization.id).grants_claimed == 1

    def test_members_cannot_claim_and_unready_billing_does_not_consume_grant(self) -> None:
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save(update_fields=["level"])
        assert self.client.post(self.url, {}, format="json").status_code == 403
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save(update_fields=["level"])
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(
                ready=False,
                continuation=TrialContinuation.PAYMENT,
            ),
        ):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()

    def test_failed_billing_read_does_not_consume_grant(self) -> None:
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=TimeoutError()):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
        ):
            response = self.client.post(self.url, {}, format="json")
        assert response.status_code == 200, response.content
        grant = SignalTrialGrant.objects.for_team(self.team.pk).get()
        assert response.json()["grant_id"] == str(grant.id)
        assert response.json()["grant_status"] == "active"

    def test_flag_off_hides_offer_but_keeps_existing_grant_visible_and_idempotent(self) -> None:
        with patch(
            "products.signals.backend.trial.billing.TrialBilling.status",
            return_value=TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT),
        ):
            response = self.client.post(self.url, {}, format="json")
            assert response.status_code == 200
            grant_id = response.json()["grant_id"]
            self.flag_mock.assert_called_with(
                "self-driving-ubp",
                str(self.organization.id),
                groups={"organization": str(self.organization.id)},
                group_properties={"organization": {"id": str(self.organization.id)}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
            self.flag_mock.return_value = False
            status = self.client.get(self.url).json()
            assert status["enabled"]
            assert status["grant_status"] == "active"
            assert not status["eligible"]
            other = Team.objects.create(organization=self.organization, name="Other project")
            other_url = f"/api/projects/{other.id}/signals/trial/"
            assert not self.client.get(other_url).json()["enabled"]
            assert self.client.post(other_url, {}, format="json").status_code == 400
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=TimeoutError()):
            retry = self.client.post(self.url, {}, format="json")
        assert retry.status_code == 200
        assert retry.json()["grant_id"] == grant_id
        assert SignalTrialOrganization.objects.get(organization_id=self.organization.id).grants_claimed == 1


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

    @parameterized.expand([({},), ({"deactivated": True},), ({"has_active_subscription": True, "products": []},)])
    def test_missing_billing_status_does_not_authorize_work(self, billing: dict[str, object]) -> None:
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch("products.signals.backend.trial.billing.BillingManager.get_billing", return_value=billing),
        ):
            status = TrialBilling(Mock(spec=Organization)).status()
        assert not status.ready
        assert not status.paid_authorized
