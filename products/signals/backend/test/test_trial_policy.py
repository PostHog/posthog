from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalScoutConfig
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.limits import TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.scouts import trial_scout_runtime


class TestTrialPolicy(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def admit(self, *, report_id: UUID | None = None) -> TrialFunding:
        return self.policy.admit(paid_authorized=False, report_id=report_id)

    def test_duplicate_and_child_activation_share_lifetime_grant(self) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        assert TrialPolicy(child).claim(user_id=self.user.pk).id == grant.id
        assert self.policy.claim(user_id=self.user.pk).id == grant.id
        assert self.policy.organization_grants_claimed() == 1

    @parameterized.expand([("",), ("cost_limit",), ("report_limit",)])
    def test_project_transfer_preserves_lifetime_grant_and_limits(self, exhaustion_reason: str) -> None:
        grant = self.claim()
        report_id = uuid4()
        funding = self.admit(report_id=report_id)
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        if exhaustion_reason:
            grant.exhausted_at = timezone.now()
            grant.exhaustion_reason = exhaustion_reason
            grant.save(update_fields=["exhausted_at", "exhaustion_reason"])
        destination = Organization.objects.create(name="Destination")
        for team in [self.team, child]:
            team.organization = destination
            team.save(update_fields=["organization"])

        for team in [self.team, child]:
            policy = TrialPolicy(team)
            assert policy.claim(user_id=self.user.pk).id == grant.id
            if exhaustion_reason:
                with self.assertRaisesMessage(TrialRefused, exhaustion_reason):
                    policy.admit(paid_authorized=False)
            else:
                assert policy.admit(parent=funding, report_id=report_id, paid_authorized=False) == funding
                policy.check_funding(funding)
            assert policy.organization_grants_claimed() == 0

        with TrialPolicy(self.team).publish_report(report_id, delivered=True):
            pass
        slot = SignalTrialReportReservation.objects.for_team(self.team.pk).get(report_id=report_id)
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED
        assert self.policy.organization_grants_claimed() == 1
        grant.refresh_from_db()
        assert grant.organization_id == self.organization.id

    def test_deleting_project_does_not_return_organization_slot(self) -> None:
        projects = [Team.objects.create(organization=self.organization, name=f"Project {index}") for index in range(3)]
        for team in projects:
            TrialPolicy(team).claim(user_id=self.user.pk)
        deleted_id = projects[0].pk
        projects[0].delete()
        assert SignalTrialGrant.objects.for_team(deleted_id, canonical=True).exists()
        with self.assertRaisesMessage(TrialRefused, "organization_limit"):
            self.policy.claim(user_id=self.user.pk)

    def test_unknown_flag_retains_confirmed_decision_but_cannot_claim(self) -> None:
        assert self.policy.flag_decision().enabled is True
        with CaptureQueriesContext(connection) as queries:
            assert self.policy.flag_decision().enabled is True
        assert not any(query["sql"].startswith("UPDATE") for query in queries)
        self.flag_mock.side_effect = RuntimeError("unavailable")
        assert self.policy.flag_decision().enabled is True
        with self.assertRaisesMessage(TrialRefused, "flag_unavailable"):
            self.policy.claim(user_id=self.user.pk)
        self.flag_mock.side_effect = None
        self.flag_mock.return_value = False
        assert self.policy.flag_decision().enabled is False

    @parameterized.expand(
        [
            ("free", True, TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT), True),
            ("payment_setup", True, TrialBillingStatus(ready=True, continuation=TrialContinuation.PAYMENT), False),
            ("disabled", False, None, False),
            ("unknown_flag", None, None, False),
            ("failed_flag", RuntimeError("flag unavailable"), None, False),
            ("paid", True, TrialBillingStatus(ready=True, continuation=TrialContinuation.PAID), False),
            ("zero_limit", True, TrialBillingStatus(ready=True, continuation=TrialContinuation.LIMIT), False),
            (
                "unsubscribed_product",
                True,
                TrialBillingStatus(ready=True, continuation=TrialContinuation.ENABLE),
                False,
            ),
            (
                "unknown_billing",
                True,
                TrialBillingStatus(ready=False, continuation=TrialContinuation.UNAVAILABLE),
                False,
            ),
            ("unready_billing", True, TrialBillingStatus(ready=False, continuation=TrialContinuation.PAYMENT), False),
            ("failed_billing", True, RuntimeError("billing unavailable"), False),
        ]
    )
    def test_trial_scout_runtime_only_overrides_confirmed_free_customers(
        self,
        _name: str,
        decision: bool | None | Exception,
        billing: TrialBillingStatus | Exception | None,
        use_luna: bool,
    ) -> None:
        self.claim()
        if _name == "payment_setup":
            self.team.organization.customer_id = "cus_test"
        if isinstance(decision, Exception):
            self.flag_mock.side_effect = decision
        else:
            self.flag_mock.return_value = decision
        with patch("products.signals.backend.trial.scouts.TrialBilling.status") as billing_status:
            if isinstance(billing, Exception):
                billing_status.side_effect = billing
            else:
                billing_status.return_value = billing
            runtime = trial_scout_runtime(self.team)
        if use_luna:
            assert runtime is not None
            assert runtime.runtime_adapter == "codex"
            assert runtime.model == "gpt-6-luna"
        else:
            assert runtime is None

    def test_activation_pauses_excess_scouts_and_preserves_user_pause(self) -> None:
        scouts = [SignalScoutConfig.objects.create(team=self.team, skill_name=f"scout-{index}") for index in range(5)]
        paused = SignalScoutConfig.objects.create(team=self.team, skill_name="paused", enabled=False)
        self.claim()
        for scout in scouts:
            scout.refresh_from_db()
        paused.refresh_from_db()
        assert [scout.enabled for scout in scouts] == [True, True, True, False, False]
        assert scouts[-1].pause_reason == SignalScoutConfig.PauseReason.TRIAL_SCOUT_LIMIT
        assert paused.status == SignalScoutConfig.Status.PAUSED_BY_USER

    @parameterized.expand([(5,), (10,)])
    def test_report_slots_release_only_before_delivery(self, report_limit: int) -> None:
        grant = self.policy.claim(user_id=self.user.pk, limits=TrialLimits(report_limit=report_limit))
        reports = [uuid4() for _ in range(report_limit + 1)]
        for report_id in reports[:report_limit]:
            self.admit(report_id=report_id)
        with self.assertRaisesMessage(TrialRefused, "report_limit"):
            self.admit(report_id=reports[-1])
        with self.policy.publish_report(reports[0], delivered=False):
            pass
        self.admit(report_id=reports[-1])
        for report_id in reports[1:]:
            with self.policy.publish_report(report_id, delivered=True):
                pass
            with self.policy.publish_report(report_id, delivered=False):
                pass
        grant.refresh_from_db()
        assert grant.exhaustion_reason == "report_limit"
        with self.assertRaisesMessage(TrialRefused, "report_limit"):
            self.admit()

    def test_publication_rollback_preserves_reservation(self) -> None:
        self.claim()
        report_id = uuid4()
        self.admit(report_id=report_id)

        def failed_write() -> None:
            raise ValueError("publish failed")

        with self.assertRaisesMessage(ValueError, "publish failed"):
            with self.policy.publish_report(report_id, delivered=True):
                failed_write()
        with self.policy.publish_report(report_id, delivered=True):
            pass

    def test_editing_historical_report_does_not_consume_its_new_research_slot(self) -> None:
        historical = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Original")
        self.claim()
        self.admit(report_id=historical.id)
        SignalReport.objects.filter(team=self.team, id=historical.id).update(status=SignalReport.Status.IN_PROGRESS)
        historical.title = "Edited"
        historical.save(update_fields=["title"])
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=historical.id)
        assert slot.status == SignalTrialReportReservation.Status.RESERVED
        historical.refresh_from_db()
        assert historical.status == SignalReport.Status.IN_PROGRESS
        historical.status = SignalReport.Status.READY
        historical.save(update_fields=["status"])
        slot.refresh_from_db()
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED

    @parameterized.expand([(True,), (False,)])
    def test_direct_report_retries_hold_slot_until_last_attempt_finishes(self, tracked: bool) -> None:
        self.claim()
        operation = self.admit()
        report = uuid4()
        first, second = (uuid4(), uuid4()) if tracked else (None, None)
        self.policy.reserve_direct_report(operation, report, run_id=first)
        self.policy.reserve_direct_report(operation, report, run_id=second)
        if tracked:
            self.policy.reserve_direct_report(operation, report, run_id=first)
        with self.policy.publish_report(report, delivered=False):
            pass
        self.policy.finish_direct_report_attempt(report, run_id=first)
        if tracked:
            self.policy.finish_direct_report_attempt(report, run_id=first)
        slot = SignalTrialReportReservation.objects.for_team(self.team.pk).get(report_id=report)
        assert slot.status == SignalTrialReportReservation.Status.RESERVED
        assert slot.active_attempts == 1
        with self.policy.publish_report(report, delivered=True):
            pass
        self.policy.finish_direct_report_attempt(report, run_id=second)
        slot.refresh_from_db()
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED
        assert slot.active_attempts == 0
        assert slot.attempt_run_ids == []

    @parameterized.expand([(True,), (False,)])
    def test_scout_cap_is_shared_with_environments_and_supports_swapping(self, enabled: bool) -> None:
        self.claim()
        self.flag_mock.return_value = enabled
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        scouts = [SignalScoutConfig.objects.create(team=child, skill_name=f"scout-{i}") for i in range(4)]
        if not enabled:
            assert all(scout.enabled for scout in scouts)
            return
        assert [scout.enabled for scout in scouts] == [True, True, True, False]
        scouts[-1].enabled = True
        with self.assertRaises(ValidationError):
            scouts[-1].save(update_fields=["enabled"])
        scouts[-1].refresh_from_db()
        scouts[0].enabled = False
        scouts[0].save(update_fields=["enabled"])
        scouts[-1].enabled = True
        scouts[-1].save(update_fields=["enabled"])
        assert SignalScoutConfig.objects.for_team(self.team.pk).filter(enabled=True).count() == 3

    def test_admitted_report_pass_keeps_trial_funding_after_flag_off(self) -> None:
        grant = self.claim()
        report = uuid4()
        parent = self.admit(report_id=report)
        grant.settled_microusd = grant.allowance_microusd
        grant.exhausted_at = timezone.now()
        grant.exhaustion_reason = "cost_limit"
        grant.save()
        self.flag_mock.return_value = False
        child = self.policy.admit(
            parent=parent,
            report_id=report,
            paid_authorized=True,
        )
        assert child.funding == "trial"
        assert child.grant_id == parent.grant_id
        self.policy.check_funding(parent)
        assert self.admit().funding == "existing"
        assert self.policy.reserve_report_layers(report, [uuid4() for _ in range(grant.report_limit + 1)])
        self.policy.reserve_direct_report(parent, uuid4())
        assert SignalTrialReportReservation.objects.for_team(self.team.id).count() == 1
        with self.policy.publish_report(report, delivered=True):
            pass
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report).status == "consumed"

    @parameterized.expand([(False, "released"), (True, "consumed")])
    def test_deletion_releases_only_undelivered_report_slots(self, delivered: bool, status: str) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        self.admit(report_id=report.id)
        if delivered:
            report.status = SignalReport.Status.READY
            report.save(update_fields=["status"])
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == status
