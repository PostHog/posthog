from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import close_old_connections
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.exceptions import QuotaLimitExceeded

from products.signals.backend.facade.api import emit_signal
from products.signals.backend.facade.trial import task_trial_admission
from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import SignalReport, SignalSpend, SignalTeamConfig
from products.signals.backend.spend import complete_signal_pipeline, finish_report_spend, record_llm_spend
from products.signals.backend.task_run_artefacts import record_report_task
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding, signal_funding
from products.signals.backend.trial.policy import TrialRefused
from products.signals.backend.trial.reports import prepare_report_pass
from products.signals.backend.trial.signals import admit_signal
from products.tasks.backend.models import Task, TaskRun


class TestSignalAdmission(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.quota = self.enterContext(
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=False)
        )
        self.flags = self.enterContext(
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "self-driving-quota-enforcement",
            )
        )

    def _reach_limit(self, limit: str) -> None:
        if limit == "billing":
            self.quota.return_value = True
        else:
            SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"max_reports_per_day": 1})
            SignalReport.objects.create(
                team=self.team, status=SignalReport.Status.READY, first_visible_at=timezone.now()
            )

    @parameterized.expand([(steering, limit) for steering in (False, True) for limit in ("billing", "daily")])
    def test_limited_direct_signal_is_dropped_before_steering_or_dispatch(self, steering: bool, limit: str) -> None:
        self._reach_limit(limit)
        signal_id = str(uuid4())
        with (
            patch("products.signals.backend.facade.api.SignalSourceConfig.is_source_enabled", return_value=True),
            patch("products.signals.backend.facade.api.async_connect", new_callable=AsyncMock) as connect,
            patch(
                "products.signals.backend.emission.direct_gate.afetch_source_config", new_callable=AsyncMock
            ) as config,
            patch("products.signals.backend.emission.pipeline._create_message", new_callable=AsyncMock) as provider,
        ):
            config.return_value = {"actionability_prompt": "Find errors"} if steering else {}
            result = async_to_sync(emit_signal)(
                team=self.team,
                signal_id=signal_id,
                source_product="error_tracking",
                source_type="issue_created",
                source_id="synthetic-issue",
                description="An application error",
                extra={"fingerprint": "synthetic-fingerprint"},
            )
        assert result is False
        config.assert_not_awaited()
        provider.assert_not_awaited()
        connect.assert_not_awaited()
        assert not SignalSpend.objects.for_team(self.team.id).filter(signal_id=signal_id).exists()

    @parameterized.expand([("billing",), ("daily",)])
    def test_admitted_signal_retries_and_starts_report_after_limit_changes(self, limit: str) -> None:
        signal_id = str(uuid4())
        admit_signal(team=self.team, signal_id=signal_id)
        funding = signal_funding(self.team.id, signal_id)
        assert funding is not None and funding.implementation_allowed
        self._reach_limit(limit)
        admit_signal(team=self.team, signal_id=signal_id)
        assert signal_funding(self.team.id, signal_id) == funding
        with self.assertRaises((QuotaLimitExceeded, TrialRefused)):
            admit_signal(team=self.team, signal_id=str(uuid4()))

        report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first", signal_id=signal_id)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first", signal_id=signal_id)
        report.refresh_from_db()
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["implementation_allowed"] is True
        task = Task.objects.create(
            team=self.team, title="Synthetic fix", origin_product="signal_report", signal_report=report
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with task_trial_admission(
            team=self.team, origin="signal_report", report_id=report.id, continue_admitted_pipeline=True
        ):
            run = task.create_run(environment=TaskRun.Environment.CLOUD)
        assert run.state["self_driving_funding"]["funding"] == funding.funding
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=signal_id)
        with self.assertRaises((QuotaLimitExceeded, TrialRefused)):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="later", signal_id=signal_id)

        with self.assertRaises((QuotaLimitExceeded, TrialRefused)):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="manual")

    @parameterized.expand([(legacy, existing) for legacy in (False, True) for existing in (False, True)])
    def test_admitted_signal_starts_report_after_limit_changes(self, legacy_trial: bool, existing_report: bool) -> None:
        self.flags.side_effect = lambda key, *a, **kw: (
            key == "self-driving-quota-enforcement" or (legacy_trial and key == "self-driving-free-trial")
        )
        first, next_signal = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team)
        if existing_report:
            admit_signal(team=self.team, signal_id=first)
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first", signal_id=first)
            finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=first)
        admit_signal(team=self.team, signal_id=next_signal)
        self.quota.return_value = True
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="refresh", signal_id=next_signal)
        report.refresh_from_db()
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["report_pass_key"] == "refresh"
        assert report.self_driving_funding["implementation_allowed"] is not legacy_trial

    def test_existing_open_receipt_continues_after_limit_changes(self) -> None:
        signal_id = str(uuid4())
        generation = AsyncMock(return_value=MagicMock())
        with patch("products.signals.backend.llm_spend._settle_generation", new_callable=AsyncMock, return_value=None):
            async_to_sync(generate_with_spend)(
                generation(), gateway=None, team_id=self.team.id, signal_id=signal_id, stage="actionability"
            )
        generation.assert_awaited_once()
        self.quota.return_value = True
        admit_signal(team=self.team, signal_id=signal_id)
        assert SignalSpend.objects.for_team(self.team.id).filter(signal_id=signal_id).count() == 1

    @parameterized.expand(
        [(state, exempt) for state in ("settled", "pending_accounting", "legacy_finalized") for exempt in (False, True)]
    )
    def test_finished_signal_cannot_be_readmitted(self, state: str, exempt: bool) -> None:
        signal_id = str(uuid4())
        admit_signal(team=self.team, signal_id=signal_id, billing_exempt=exempt)
        if state == "pending_accounting":
            record_llm_spend(team_id=self.team.id, signal_id=signal_id, token_cost_microusd=None, stage="test")
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        if state == "pending_accounting":
            assert spend.finalization_requested_at is not None
            assert spend.finalized_at is None
        elif state == "legacy_finalized":
            assert spend.finalized_at is not None
            spend.finalization_requested_at = None
            spend.save(update_fields=["finalization_requested_at"])
        with self.assertRaises(TrialRefused):
            admit_signal(team=self.team, signal_id=signal_id, billing_exempt=exempt)
        self.quota.return_value = True
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
        with self.assertRaises(QuotaLimitExceeded):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="new", signal_id=signal_id)

    def test_operator_continuation_remains_exempt(self) -> None:
        self.quota.return_value = True
        self._reach_limit("daily")
        signal_id = str(uuid4())
        token = direct_report_funding.set((self.team.id, TrialFunding(funding="operator")))
        try:
            admit_signal(team=self.team, signal_id=signal_id)
        finally:
            direct_report_funding.reset(token)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.billing_exempt

    def test_concurrent_retries_keep_one_admission(self) -> None:
        signal_id = str(uuid4())
        ready = Barrier(2)

        def read_quota(*args):
            ready.wait(timeout=10)
            return False

        def submit() -> None:
            try:
                admit_signal(team=self.team, signal_id=signal_id)
            finally:
                close_old_connections()

        self.quota.side_effect = read_quota
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)
        assert SignalSpend.objects.for_team(self.team.id).filter(signal_id=signal_id).count() == 1
        assert signal_funding(self.team.id, signal_id) is not None

    @parameterized.expand([(False,), (True,)])
    def test_accepted_system_signal_does_not_make_customer_report_free(self, previous_operator_run: bool) -> None:
        self.quota.return_value = True
        signal_id = str(uuid4())
        admit_signal(team=self.team, signal_id=signal_id, billing_exempt=True)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.billing_exempt
        self._reach_limit("daily")
        admit_signal(team=self.team, signal_id=signal_id, billing_exempt=True)
        with self.assertRaises(TrialRefused):
            admit_signal(team=self.team, signal_id=str(uuid4()), billing_exempt=True)
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
        if previous_operator_run:
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="operator", operator_rerun=True)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted", signal_id=signal_id)
        report.refresh_from_db()
        assert report.billing_exempt_reason is None
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["funding"] == "existing"
