from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models import OrganizationMembership

from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialOrganization


@override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
class TestTrialAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.url = f"/api/projects/{self.team.pk}/signals/trial/"
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)

    @parameterized.expand([(TrialContinuation.PAYMENT,), (TrialContinuation.LIMIT,), (TrialContinuation.PAID,)])
    def test_all_cohorts_can_explicitly_claim_once(self, continuation: TrialContinuation) -> None:
        def billing_status(*, grant_id=None) -> TrialBillingStatus:
            return TrialBillingStatus(ready=True, migrated=grant_id is not None, continuation=continuation)

        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=billing_status):
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
                migrated=False,
                continuation=TrialContinuation.PAYMENT,
            ),
        ):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        assert not SignalTrialGrant.objects.for_team(self.team.pk).exists()

    def test_failed_billing_acknowledgement_retries_same_grant(self) -> None:
        ready = TrialBillingStatus(ready=True, migrated=False, continuation=TrialContinuation.PAYMENT)
        migrated = TrialBillingStatus(ready=True, migrated=True, continuation=TrialContinuation.PAYMENT)
        with patch("products.signals.backend.trial.billing.TrialBilling.status", side_effect=[ready, TimeoutError()]):
            assert self.client.post(self.url, {}, format="json").status_code == 400
        grant = SignalTrialGrant.objects.for_team(self.team.pk).get()
        with patch("products.signals.backend.trial.billing.TrialBilling.status", return_value=migrated):
            response = self.client.post(self.url, {}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["grant_id"] == str(grant.id)
        assert response.json()["grant_status"] == "active"
