from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

import httpx
from anthropic import APIStatusError
from asgiref.sync import async_to_sync

from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost

from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import SignalReport
from products.signals.backend.spend import record_llm_spend
from products.signals.backend.trial.direct_reports import trial_report_reservation_sync
from products.signals.backend.trial.llm_execution import TrialLLMExecution
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import prepare_report_pass, report_trial_context
from products.tasks.backend.models import Task, TaskRun


class TestTrialReportExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def test_failed_generation_registration_prevents_provider_request(self) -> None:
        self.claim()
        generation = AsyncMock()
        with patch("products.signals.backend.spend._save_spend", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="summarization",
                )
        generation.assert_not_awaited()

    def test_http_failure_preserves_gateway_receipt_and_charges_failed_attempt(self) -> None:
        grant = self.claim()
        error = APIStatusError(
            "provider error",
            response=httpx.Response(
                500,
                request=httpx.Request("POST", "https://gateway.example.com/v1/messages"),
                headers={"request-id": "failed-request"},
            ),
            body=None,
        )
        generation = AsyncMock(side_effect=error)
        with patch(
            "products.signals.backend.llm_spend.fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
        ):
            with self.assertRaises(APIStatusError):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="summarization",
                )
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0
        assert grant.settled_microusd == 123

    def test_report_pass_funding_survives_retry_exhaustion_and_paid_handoff(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first-pass")
        task = Task.objects.create(
            team=self.team, title="Research", origin_product="signal_report", signal_report_id=report.id
        )
        run = task.create_run(extra_state={"ai_stage": "research"})
        run.state["sandbox_provisioning_started"] = True
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["state", "status"])
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        with patch(
            "products.signals.backend.trial.reports.paid_trial_continuation_authorized",
            side_effect=RuntimeError("billing unavailable"),
        ):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first-pass")
        with patch("products.signals.backend.trial.reports.paid_trial_continuation_authorized", return_value=True):
            with self.assertRaisesMessage(TrialRefused, "report_pass_in_progress"):
                prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="overlapping-pass")
        context = report_trial_context.set((self.team.id, str(report.id)))
        try:
            finalization = TrialLLMExecution.prepare(
                team_id=self.team.id, gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key")
            )
            assert finalization is not None and finalization.funding.grant_id == grant.id
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                task.create_run(extra_state={"ai_stage": "research"})
        finally:
            report_trial_context.reset(context)
        report.status = SignalReport.Status.READY
        report.save(update_fields=["status"])
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == "consumed"
        with patch("products.signals.backend.trial.reports.paid_trial_continuation_authorized", return_value=True):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="second-pass")
        SignalReport.objects.filter(id=report.id, team_id=self.team.id).update(status=SignalReport.Status.IN_PROGRESS)
        paid_run = task.create_run(extra_state={"ai_stage": "research"})
        assert paid_run.state["self_driving_funding"]["funding"] == "paid"
        assert run.state["self_driving_funding"]["funding"] == "trial"

    def test_paid_direct_retry_does_not_consume_released_trial_slot(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
        trial_run = task.create_run()
        with trial_report_reservation_sync(
            team=self.team, run_id=trial_run.id, emission_key="same-report"
        ) as report_id:
            assert report_id is not None
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report_id)
        assert slot.status == "released"
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="scout",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        with patch("products.signals.backend.facade.trial.paid_trial_continuation_authorized", return_value=True):
            paid_run = task.create_run()
        with trial_report_reservation_sync(team=self.team, run_id=paid_run.id, emission_key="same-report"):
            report = SignalReport.objects.create(id=report_id, team=self.team, status=SignalReport.Status.READY)
        slot.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        assert slot.status == "released"
