from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.models import OrganizationMembership, Team

from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialGrant


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

    @parameterized.expand(
        [(10_000_000, 5, 20_000_000, 10), (20_000_000, 10, 10_000_000, 5), (20_000_000, 10, None, None)]
    )
    def test_plan_limits_are_snapshotted_at_activation(
        self, allowance: int, reports: int, next_allowance: int | None, next_reports: int | None
    ) -> None:
        customer = {
            "deactivated": False,
            "has_active_subscription": False,
            "available_product_features": [
                {"key": "self_driving_trial_allowance_microusd", "limit": allowance},
                {"key": "self_driving_trial_reports", "limit": reports},
            ],
            "products": [
                {
                    "type": "inbox",
                    "usage_key": "signals_credits",
                    "subscribed": False,
                    "free_allocation": 0,
                    "usage_limit": 0,
                }
            ],
        }
        with (
            patch("products.signals.backend.trial.billing.get_cached_instance_license", return_value=Mock()),
            patch(
                "products.signals.backend.trial.billing.BillingManager.get_billing",
                return_value=customer,
            ),
        ):
            offer = self.client.get(self.url).json()
            assert offer["allowance_microusd"] == allowance
            assert offer["report_limit"] == reports
            started = self.client.post(
                self.url, {"allowance_microusd": 100_000_000, "report_limit": 100}, format="json"
            )
            assert started.status_code == 200, started.content
            assert started.json()["allowance_microusd"] == allowance
            assert started.json()["report_limit"] == reports
            grant_id = started.json()["grant_id"]
            SignalTrialGrant.objects.for_team(self.team.pk).update(settled_microusd=3_000_000)
            customer["available_product_features"] = [
                {"key": "self_driving_trial_allowance_microusd", "limit": next_allowance},
                {"key": "self_driving_trial_reports", "limit": next_reports},
            ]
            for response in [self.client.get(self.url), self.client.post(self.url, {}, format="json")]:
                assert response.status_code == 200, response.content
                status = response.json()
                assert status["grant_id"] == grant_id
                assert status["allowance_microusd"] == allowance
                assert status["report_limit"] == reports
                assert status["used_microusd"] == 3_000_000
            assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1

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
        assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1

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
        assert SignalTrialGrant.objects.unscoped().filter(organization_id=self.organization.id).count() == 1
