from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import time_machine
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
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.signals.backend.trial.limits import TrialLimits
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.usage import trial_usage
from products.tasks.backend.facade.billing import TaskTokenUsageUnavailable, locked_task_run_spend
from products.tasks.backend.facade.testing import create_completed_task_sandbox_session
from products.tasks.backend.models import Task, TaskRun


class TestTrialAccounting(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)
        self.organization.usage = {"signals_spend_credits": {"billing_start_date": "2026-01-01"}}
        self.organization.save(update_fields=["usage"])

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
        pending = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert pending.accounting_pending
        assert not pending.accounting_failed
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
        assert trial_usage(grant).spend_microusd == 10_000_001
        assert trial_usage(grant).exhaustion_reason(grant) == "cost_limit"
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert (spend.finalized_at is not None) is finalized
        assert spend.billing_exempt

    def test_pending_cost_does_not_freeze_admission_and_settles_without_regrant(self) -> None:
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
        with time_machine.travel(timezone.now() + timedelta(minutes=3), tick=False):
            assert self.policy.admit(paid_authorized=False).grant_id == grant.id
        record_llm_spend(
            "late", team_id=self.team.id, signal_id=signal_id, stage="short", source_id="late", token_cost_microusd=101
        )
        assert self.policy.admit(paid_authorized=False).grant_id == grant.id
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == 101

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
        assert get_signals_spend_billing_credits_by_team(
            timezone.now() - timedelta(days=1),
            timezone.now() + timedelta(days=1),
        ) == [(self.team.id, 20)]

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
        assert trial_usage(grant).spend_microusd == 0
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.trial_grant_id is None
        assert spend.spend == Decimal("0.0101")

    @parameterized.expand([("trial", True, 0), ("paid", False, 10_000_000), ("trial_spillover", True, 10_000_000)])
    def test_tasks_charge_shared_inference_compute_and_task_fee_once(
        self, _name: str, trial: bool, prior_spend: int
    ) -> None:
        grant = self.claim()
        if prior_spend:
            record_llm_spend(
                team_id=self.team.id,
                signal_id=str(uuid4()),
                stage="research",
                token_cost_microusd=prior_spend,
                trial_grant_id=str(grant.id),
            )
        task = Task.objects.create(team=self.team, title="Trial research", origin_product="signal_report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.FAILED,
            environment=TaskRun.Environment.CLOUD,
            state={
                "self_driving_funding": {
                    "funding": "trial" if trial else "paid",
                    "grant_id": str(grant.id) if trial else None,
                },
                "token_cost": {"model": {"provider": {"cost_microusd": 200_001}}},
                "unprocessed_request_ids": [],
            },
        )
        create_completed_task_sandbox_session(team_id=self.team.id, task_run_id=run.id, duration=timedelta(seconds=100))
        signal_id = str(uuid4())
        with patch("products.signals.backend.spend.trial_spend_exempt", return_value=False):
            for _ in range(2):
                record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=signal_id)
        with patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock):
            complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        with locked_task_run_spend(team_id=self.team.id, run_id=run.id) as cost:
            assert cost.compute_cost_microusd > 0
            expected = 200_001 + 40_000 + cost.compute_cost_microusd
        grant.refresh_from_db()
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert trial_usage(grant).spend_microusd == prior_spend + (expected if trial else 0)
        assert spend.spend == Decimal(expected) / 10_000
        assert spend.billing_exempt is trial
        assert spend.finalized_at is not None
        assert get_signals_spend_billing_credits_by_team(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        ) == ([] if trial else [(self.team.id, round(spend.spend))])

    def test_accepted_pipeline_keeps_trial_funding_and_exempts_spillover(self) -> None:
        grant = self.claim()
        funding = self.policy.admit(paid_authorized=False)
        for amount in (grant.allowance_microusd, 200_000):
            signal_id = str(uuid4())
            record_llm_spend(
                team_id=self.team.id,
                signal_id=signal_id,
                stage="research",
                token_cost_microusd=amount,
                trial_grant_id=str(grant.id),
            )
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
            assert self.policy.admit(paid_authorized=True, parent=funding) == funding
        with self.assertRaisesMessage(TrialRefused, "cost_limit"):
            self.policy.admit(paid_authorized=False)
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == grant.allowance_microusd + 200_000
        assert not SignalSpend.objects.for_team(self.team.id).filter(billing_exempt=False).exists()
        assert (
            get_signals_spend_billing_credits_by_team(
                timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
            )
            == []
        )

    def test_pending_task_accounting_retries_and_releases_trial_admission(self) -> None:
        self._assert_pending_task_recovers(final_attempt=False)

    def test_pending_trial_task_can_settle_after_the_last_retry(self) -> None:
        self._assert_pending_task_recovers(final_attempt=True)

    def _assert_pending_task_recovers(self, *, final_attempt: bool) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Trial research", origin_product="signal_report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            environment=TaskRun.Environment.CLOUD,
            state={
                "self_driving_funding": {"funding": "trial", "grant_id": str(grant.id)},
                "token_cost": {},
                "unprocessed_request_ids": ["late-request"],
            },
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=str(uuid4()))
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert spend.accounting_pending
        assert not spend.accounting_failed
        grant.refresh_from_db()
        with (
            patch("products.tasks.backend.facade.billing.process_pending_gateway_usage"),
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
        ):
            if final_attempt:
                complete_task_spend(team_id=self.team.id, run_id=str(run.id), final_attempt=True)
            else:
                with self.assertRaises(TaskTokenUsageUnavailable):
                    complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        waiting = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert waiting.accounting_pending
        assert not waiting.accounting_failed
        run.state["unprocessed_request_ids"] = []
        run.state["token_cost"] = {"model": {"provider": {"cost_microusd": 100_000}}}
        run.save(update_fields=["state"])
        with (
            patch("products.tasks.backend.facade.billing.process_pending_gateway_usage"),
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
        ):
            complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        grant = SignalTrialGrant.objects.for_team(self.team.id, canonical=True).get(id=grant.id)
        assert spend.finalized_at is not None
        assert not spend.accounting_failed
        assert not spend.accounting_pending
        assert trial_usage(grant).spend_microusd == 140_000
        assert self.policy.admit(paid_authorized=False).grant_id == grant.id
