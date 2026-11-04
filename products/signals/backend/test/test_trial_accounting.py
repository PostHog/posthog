from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import (
    complete_signal_pipeline,
    complete_task_spend,
    record_llm_spend,
    record_task_spend,
)
from products.signals.backend.spend_billing import spend_billing_credits_by_team
from products.signals.backend.trial.limits import TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.tasks.backend.facade.billing import locked_task_run_spend
from products.tasks.backend.facade.testing import create_completed_task_sandbox_session
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
            assert self.policy.admit(paid_authorized=authorized).funding == ("paid" if exhausted else "trial")

    @parameterized.expand([(True,), (False,)])
    def test_late_generation_cost_is_counted_once_after_flag_off(self, finalized: bool) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=None,
            source_id="attempt",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        if finalized:
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        self.flag_mock.return_value = False
        for _ in range(2):
            record_llm_spend(
                "gateway-request",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="short",
                source_id="attempt",
                token_cost_microusd=10_000_001,
            )
        with self.assertRaisesMessage(ValueError, "Register the request before settling its cost"):
            record_llm_spend(
                "gateway-request",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="short",
                source_id="attempt",
                token_cost_microusd=10_000_001,
                strict=True,
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 10_000_001
        assert grant.incomplete_sources == 0
        assert grant.exhaustion_reason == "cost_limit"
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert (spend.finalized_at is not None) is finalized
        assert spend.billing_exempt

    def test_missing_cost_pauses_admission_then_recovers_without_regrant(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=None,
            source_id="late",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(
            incomplete_since=timezone.now() - timedelta(minutes=3)
        )
        with self.assertRaisesMessage(TrialRefused, "accounting_pending"):
            self.policy.admit(paid_authorized=False)
        record_llm_spend(
            "late", team_id=self.team.id, signal_id=signal_id, stage="short", source_id="late", token_cost_microusd=101
        )
        assert self.policy.admit(paid_authorized=False).grant_id == grant.id
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0
        assert grant.settled_microusd == 101

    def test_trial_spend_is_exempt_but_later_paid_spend_is_billed(self) -> None:
        grant = self.claim()
        for trial, amount in [(True, 10_000_000), (False, 200_000)]:
            signal_id = str(uuid4())
            with patch("products.signals.backend.spend.trial_spend_exempt", return_value=False):
                record_llm_spend(
                    team_id=self.team.id,
                    signal_id=signal_id,
                    stage="short",
                    token_cost_microusd=amount,
                    trial_grant_id=str(grant.id) if trial else None,
                )
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        assert spend_billing_credits_by_team(
            timezone.now() - timedelta(days=1),
            timezone.now() + timedelta(days=1),
            cutoffs={self.team.organization_id: timezone.now() - timedelta(days=1)},
        ) == {self.team.id: 20}

    def test_existing_generation_cost_cannot_be_reassigned_to_new_trial(self) -> None:
        signal_id = str(uuid4())
        record_llm_spend(team_id=self.team.id, signal_id=signal_id, stage="short", token_cost_microusd=101)
        grant = self.claim()
        with self.assertRaisesMessage(ValueError, "Generation funding cannot change"):
            record_llm_spend(
                team_id=self.team.id,
                signal_id=signal_id,
                stage="short",
                token_cost_microusd=None,
                source_id="new-attempt",
                trial_grant_id=str(grant.id),
                strict=True,
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 0
        assert grant.incomplete_sources == 0
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.trial_grant_id is None
        assert spend.spend == Decimal("0.0101")

    def test_tasks_charge_shared_inference_compute_and_task_fee_once(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Trial research", origin_product="signal_report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.FAILED,
            environment=TaskRun.Environment.CLOUD,
            state={
                "self_driving_funding": {"funding": "trial", "grant_id": str(grant.id)},
                "token_cost": {"model": {"provider": {"cost_microusd": 200_001}}},
                "unprocessed_request_ids": [],
            },
        )
        create_completed_task_sandbox_session(team_id=self.team.id, task_run_id=run.id, duration=timedelta(seconds=100))
        signal_id = str(uuid4())
        for _ in range(2):
            record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=signal_id)
        with patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock):
            complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        with locked_task_run_spend(team_id=self.team.id, run_id=run.id) as cost:
            assert cost.compute_cost_microusd > 0
            expected = 200_001 + 40_000 + cost.compute_cost_microusd
        grant.refresh_from_db()
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert grant.settled_microusd == expected
        assert spend.spend == Decimal(expected) / 10_000
        assert spend.billing_exempt
        assert spend.finalized_at is not None
