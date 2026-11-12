from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSpend
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY
from products.signals.backend.scout_harness.team_limits import max_enabled_scouts_for_team, resolve_team_metadata
from products.signals.backend.trial.billing import TrialBillingStatus, TrialContinuation
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.limits import TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.scouts import trial_scout_runtime
from products.signals.backend.usage import trial_usage
from products.skills.backend.models.skills import LLMSkill

_INBOX_VALIDATION = "signals-scout-inbox-validation"


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
        report_id = SignalReport.objects.create(team=self.team).id
        funding = self.admit(report_id=report_id)
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        if exhaustion_reason:
            self.exhaust(grant, exhaustion_reason)
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
                assert policy.admit(paid_authorized=True).funding == "paid"
            else:
                assert policy.admit(parent=funding, paid_authorized=False) == funding
            assert policy.organization_grants_claimed() == 0

        assert self.policy.organization_grants_claimed() == 1
        grant.refresh_from_db()
        assert grant.organization_id == self.organization.id

    def test_one_organization_claim_survives_project_deletion(self) -> None:
        project = Team.objects.create(organization=self.organization, name="Trial project")
        TrialPolicy(project).claim(user_id=self.user.pk)
        with self.assertRaisesMessage(TrialRefused, "organization_limit"):
            self.claim()
        deleted_id = project.pk
        project.delete()
        assert SignalTrialGrant.objects.for_team(deleted_id, canonical=True).exists()
        with self.assertRaisesMessage(TrialRefused, "organization_limit"):
            self.policy.claim(user_id=self.user.pk)

    def test_unknown_flag_retains_confirmed_decision_but_cannot_claim(self) -> None:
        grant = self.claim()
        self.exhaust(grant, "cost_limit")
        assert self.policy.flag_decision().enabled is True
        with CaptureQueriesContext(connection) as queries:
            assert self.policy.flag_decision().enabled is True
        assert not any(query["sql"].startswith("UPDATE") for query in queries)
        self.flag_mock.side_effect = RuntimeError("unavailable")
        assert self.policy.flag_decision().enabled is True
        with self.assertRaisesMessage(TrialRefused, "cost_limit"):
            self.admit()
        with self.assertRaisesMessage(TrialRefused, "flag_unavailable"):
            self.policy.claim(user_id=self.user.pk)
        self.flag_mock.side_effect = None
        self.flag_mock.return_value = False
        assert self.policy.flag_decision().enabled is False
        assert self.admit().funding == "existing"

    @parameterized.expand([("starts_later", 2, False), ("starts_today", 0, True), ("no_cutover", None, True)])
    def test_pricing_stays_off_until_the_billing_cutover(
        self, _name: str, cutover_in_days: int | None, enabled: bool
    ) -> None:
        if cutover_in_days is not None:
            cutover = timezone.now().date() + timedelta(days=cutover_in_days)
            self.organization.usage = {"signals_spend_credits": {"billing_start_date": cutover.isoformat()}}
            self.organization.save(update_fields=["usage"])
        decision = self.policy.flag_decision()
        assert (decision.enabled, decision.confirmed) == (enabled, True)

    @parameterized.expand(
        [
            ("missing", False, False, False),
            ("flag_unavailable", True, False, False),
            ("cache_unavailable", False, True, False),
            ("cutover_unreadable", False, False, True),
        ]
    )
    def test_unknown_flag_rejects_new_work_and_preserves_accepted_funding(
        self, _name: str, flag_unavailable: bool, cache_unavailable: bool, cutover_unreadable: bool
    ) -> None:
        grant = self.claim()
        funding = self.admit()
        self.exhaust(grant, "cost_limit")
        if cutover_unreadable:
            self.organization.usage = {"signals_spend_credits": {"billing_start_date": "soon"}}
            self.organization.save(update_fields=["usage"])
        else:
            self.flag_mock.return_value = None
        self.flag_mock.side_effect = RuntimeError("flag unavailable") if flag_unavailable else None
        with patch(
            "products.signals.backend.trial.policy.cache.get",
            return_value=None,
            side_effect=RuntimeError("cache unavailable") if cache_unavailable else None,
        ):
            with self.assertRaisesMessage(TrialRefused, "flag_unavailable"):
                self.admit()
            assert self.policy.admit(paid_authorized=False, parent=funding) == funding

    def exhaust(self, grant: SignalTrialGrant, reason: str) -> None:
        if reason == "cost_limit":
            SignalSpend.objects.create(
                team=self.team,
                kind=SignalSpend.Kind.AD_HOC,
                signal_id=uuid4(),
                trial_grant=grant,
                billing_exempt=True,
                spend=Decimal(grant.allowance_microusd) / 10_000,
            )
        else:
            SignalReport.objects.bulk_create(
                [
                    SignalReport(team=self.team, first_visible_at=timezone.now(), status=SignalReport.Status.READY)
                    for _ in range(grant.report_limit)
                ]
            )

    @parameterized.expand([("cost_limit",), ("report_limit",)])
    def test_exhaustion_blocks_new_work_but_accepted_pipelines_finish(self, reason: str) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team)
        funding = self.admit(report_id=report.id)
        self.exhaust(grant, reason)
        with self.assertRaisesMessage(TrialRefused, reason):
            self.admit()
        assert self.policy.admit(paid_authorized=False, parent=funding, report_id=report.id) == funding
        assert self.policy.admit(paid_authorized=False, report_id=report.id) == funding
        assert self.policy.admit(paid_authorized=True, report_id=report.id) == funding
        assert self.policy.admit(paid_authorized=True).funding == "paid"
        self.flag_mock.return_value = False
        assert self.policy.admit(paid_authorized=False, parent=funding) == funding
        assert self.admit().funding == "existing"

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
        with patch("products.signals.backend.trial.billing.TrialBilling.status") as billing_status:
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

    @parameterized.expand([("enabled_before_claim", 3), ("enabled_after_claim", 2)])
    def test_operational_scout_takes_no_trial_slot(self, _name: str, enabled_before_claim: int) -> None:
        self._operational_skill(seeded=True)
        operational = SignalScoutConfig.objects.create(team=self.team, skill_name=_INBOX_VALIDATION)
        chosen = [
            SignalScoutConfig.objects.create(
                team=self.team, skill_name=f"scout-{index}", enabled=index < enabled_before_claim
            )
            for index in range(3)
        ]
        extra = SignalScoutConfig.objects.create(team=self.team, skill_name="scout-extra", enabled=False)
        self.claim()
        for scout in chosen[enabled_before_claim:]:
            scout.enabled = True
            scout.save()

        for scout in [operational, *chosen]:
            scout.refresh_from_db()
        assert [scout.enabled for scout in [operational, *chosen]] == [True, True, True, True]
        extra.enabled = True
        with self.assertRaisesMessage(ValidationError, "The free trial allows three enabled scouts"):
            extra.save()
        with patch("products.signals.backend.scout_harness.team_limits._read_flag_payload", return_value={}):
            assert max_enabled_scouts_for_team(self.team.id) == 4

    def test_team_skill_under_an_operational_name_takes_a_trial_slot(self) -> None:
        self._operational_skill(seeded=False)
        SignalScoutConfig.objects.create(team=self.team, skill_name=_INBOX_VALIDATION)
        for index in range(2):
            SignalScoutConfig.objects.create(team=self.team, skill_name=f"scout-{index}")
        self.claim()

        third = SignalScoutConfig.objects.create(team=self.team, skill_name="scout-third", enabled=False)
        third.enabled = True
        with self.assertRaisesMessage(ValidationError, "The free trial allows three enabled scouts"):
            third.save()
        with patch("products.signals.backend.scout_harness.team_limits._read_flag_payload", return_value={}):
            assert max_enabled_scouts_for_team(self.team.id) == 3

    def _operational_skill(self, *, seeded: bool) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name=_INBOX_VALIDATION,
            description="d",
            body="b",
            metadata={"seeded_by": HARNESS_SEEDED_BY} if seeded else {},
        )

    @parameterized.expand([(None, 3), (2, 2), (10, 3)])
    def test_scout_metadata_matches_the_enforced_trial_limit(self, configured_limit: int | None, expected: int) -> None:
        self.claim()
        payload = {"default_team_config": {"max_enabled_scouts": configured_limit}}
        with patch("products.signals.backend.scout_harness.team_limits._read_flag_payload", return_value=payload):
            assert resolve_team_metadata(self.team.id).limits.max_enabled_scouts == expected
            assert max_enabled_scouts_for_team(self.team.id) == expected

    @parameterized.expand([(5,), (10,)])
    def test_report_admission_counts_running_work_and_releases_undelivered_work(self, report_limit: int) -> None:
        grant = self.policy.claim(user_id=self.user.pk, limits=TrialLimits(report_limit=report_limit))
        reports = [SignalReport.objects.create(team=self.team) for _ in range(report_limit + 1)]
        for report in reports[:report_limit]:
            self.admit(report_id=report.id)
        with self.assertRaisesMessage(TrialRefused, "report_limit"):
            self.admit(report_id=reports[-1].id)
        reports[0].status = SignalReport.Status.SUPPRESSED
        reports[0].save(update_fields=["status"])
        assert self.admit(report_id=reports[-1].id).grant_id == grant.id
        assert trial_usage(grant).running_reports == report_limit

    @parameterized.expand(
        [
            ("ready", "suppressed"),
            ("pending_input", "deleted"),
            ("failed", "deleted"),
        ]
    )
    @time_machine.travel("2026-11-08T00:00:00Z", tick=False)
    def test_report_qualification_survives_hiding_and_deletion(self, delivered_status: str, hidden_status: str) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        self.admit(report_id=report.id)
        report.refresh_from_db()
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status(delivered_status), title="Report", summary="Summary", error="Run ended"
            )
        )
        assert trial_usage(grant).reports == 1
        assert trial_usage(grant).running_reports == 0
        report.status = hidden_status
        report.save(update_fields=["status"])
        assert trial_usage(grant).reports == 1

    def test_trial_report_count_uses_first_visibility_not_later_funding(self) -> None:
        grant = self.claim()
        SignalReport.objects.create(team=self.team, first_visible_at=grant.claimed_at - timedelta(seconds=1))
        SignalReport.objects.create(
            team=self.team, first_visible_at=timezone.now(), self_driving_funding=TrialFunding(funding="paid").as_dict()
        )
        SignalReport.objects.create(team=self.team, first_visible_at=timezone.now(), billing_exempt_reason="operator")
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        SignalReport.objects.create(team=child, first_visible_at=timezone.now())
        assert trial_usage(grant).reports == 2

    @parameterized.expand([(False,), (True,)])
    def test_trial_usage_counts_known_cost_before_and_after_settlement(self, finalized: bool) -> None:
        grant = self.claim()
        SignalSpend.objects.create(
            team=self.team,
            kind=SignalSpend.Kind.AD_HOC,
            signal_id=uuid4(),
            trial_grant=grant,
            spend=Decimal("1000.0000"),
            billing_exempt=True,
            finalized_at=timezone.now() if finalized else None,
        )
        usage = trial_usage(grant)
        assert usage.spend_microusd == 10_000_000
        assert usage.settled_microusd == (10_000_000 if finalized else 0)
        with self.assertRaisesMessage(TrialRefused, "cost_limit"):
            self.admit()

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
