from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import complete_signal_pipeline, record_llm_spend, record_task_spend
from products.signals.backend.spend_billing import spend_billing_credits_by_team
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.limits import TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.tasks.backend.facade.contracts import TaskRunActualCost
from products.tasks.backend.models import Task, TaskRun


class TestTrialAccounting(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def admit(self) -> TrialFunding:
        return self.policy.admit(paid_authorized=False)

    @parameterized.expand(
        [
            (exhausted, authorized, allowance)
            for exhausted in (True, False)
            for authorized in (True, False)
            for allowance in (10_000_000, 20_000_000)
        ]
    )
    def test_paid_handoff_requires_exhaustion_and_authorization(
        self, exhausted: bool, authorized: bool, allowance: int
    ) -> None:
        grant = self.policy.claim(user_id=self.user.pk, limits=TrialLimits(allowance_microusd=allowance))
        record_llm_spend(
            "cost",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=allowance if exhausted else allowance - 1,
            trial_grant_id=str(grant.id),
        )
        if exhausted and not authorized:
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                self.policy.admit(paid_authorized=authorized)
        else:
            operation = self.policy.admit(paid_authorized=authorized)
            assert operation.funding == ("paid" if exhausted else "trial")

    def test_one_allowance_includes_late_costs_failed_runs_and_all_stages(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        for stage, cost in [("scout", 3_000_001), ("research", 4_000_002), ("implementation", 3_000_003)]:
            record_llm_spend(
                stage,
                team_id=self.team.id,
                signal_id=signal_id,
                stage=stage,
                token_cost_microusd=cost,
                trial_grant_id=str(grant.id),
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 10_000_006
        assert grant.exhaustion_reason == "cost_limit"
        self.flag_mock.return_value = False
        for _ in range(2):
            record_llm_spend(
                "implementation",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="implementation",
                token_cost_microusd=4_000_003,
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 11_000_006
        assert grant.exhaustion_reason == "cost_limit"
        assert not SignalTrialReportReservation.objects.for_team(self.team.id).exists()

    def test_missing_cost_pauses_admission_then_recovers_without_regrant(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            "late",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=None,
            trial_grant_id=str(grant.id),
        )
        SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(
            incomplete_since=timezone.now() - timedelta(minutes=3)
        )
        with self.assertRaisesMessage(TrialRefused, "accounting_pending"):
            self.admit()
        record_llm_spend("late", team_id=self.team.id, signal_id=signal_id, stage="short", token_cost_microusd=101)
        assert self.admit().grant_id == grant.id
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0
        assert grant.settled_microusd == 101

    def test_trial_sources_never_bill_but_later_paid_work_on_same_owner_does(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            "trial",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        SignalSpend.objects.for_team(self.team.id).filter(signal_id=signal_id).update(usage_based_billing=True)
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.billing_amounts == {}
        self.flag_mock.return_value = False
        record_llm_spend(
            "trial", team_id=self.team.id, signal_id=signal_id, stage="short", token_cost_microusd=11_000_000
        )
        record_llm_spend(
            "paid", team_id=self.team.id, signal_id=signal_id, stage="implementation", token_cost_microusd=200_000
        )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend.refresh_from_db()
        assert sum(spend.billing_amounts.values()) == 200_000
        assert spend_billing_credits_by_team(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        ) == {self.team.id: 20}

    def test_tasks_charge_raw_tokens_and_compute_once_without_task_fee(self) -> None:

        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Trial research", origin_product="signal_report")
        run = TaskRun.objects.create(task=task, team=self.team)
        run.state = {
            "self_driving_funding": {"funding": "trial", "grant_id": str(grant.id)},
            "token_cost": {"model": {"provider": {"cost_microusd": 200_001}}},
            "unprocessed_request_ids": [],
        }
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["state", "status"])
        signal_id = str(uuid4())
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=200_001, compute_cost_microusd=300_002, complete=True, compute_complete=True
            ),
        ):
            for _ in range(2):
                record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=signal_id)
        grant.refresh_from_db()
        assert grant.settled_microusd == 500_003
        assert grant.incomplete_sources == 0
