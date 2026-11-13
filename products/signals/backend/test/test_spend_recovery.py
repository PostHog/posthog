from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.spend import complete_signal_pipeline, record_llm_spend, record_task_spend
from products.signals.backend.spend_recovery import RECOVERY_SOURCE_LIMIT, recover_incomplete_spend, recover_spend
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.usage import trial_usage
from products.tasks.backend.facade.billing import TaskTokenUsageUnavailable, locked_task_run_spend
from products.tasks.backend.facade.testing import create_completed_task_sandbox_session
from products.tasks.backend.models import Task, TaskRun


class TestSpendRecovery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def test_missing_task_costs_wait_for_the_next_sweep_without_retry_chains(self) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Pending research",
            origin_product="signal_report",
            signal_report=report,
            internal=True,
        )
        run = task.create_run(extra_state={"ai_stage": "research", "unprocessed_request_ids": ["missing"]})
        TaskRun.objects.filter(id=run.id, team_id=self.team.id).update(status=TaskRun.Status.COMPLETED)
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        with (
            patch(
                "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
                new_callable=AsyncMock,
                return_value=None,
            ) as fetch,
            patch.object(
                recover_spend, "retry", side_effect=AssertionError("Incomplete costs must wait for the sweep")
            ),
        ):
            for _ in range(2):
                result = recover_spend.apply(args=(self.team.id, str(spend.id)), throw=False)
                assert result.failed()
                assert isinstance(result.result, TaskTokenUsageUnavailable)
        assert fetch.await_count == 2
        spend.refresh_from_db()
        assert spend.accounting_pending
        assert not spend.accounting_failed
        assert spend.finalized_at is None

    @parameterized.expand([("trial",), ("paid",), ("operator",)])
    def test_delayed_compute_settles_once_with_original_funding(self, funding: str) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Delayed sandbox cost", origin_product="signal_report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            environment=TaskRun.Environment.CLOUD,
            state={
                "self_driving_funding": {
                    "funding": funding,
                    "grant_id": str(grant.id) if funding == "trial" else None,
                },
                "sandbox_id": "test-compute-session",
                "token_cost": {"model": {"provider": {"cost_microusd": 200_001}}},
                "unprocessed_request_ids": [],
            },
        )
        with patch("products.signals.backend.spend.trial_spend_exempt", return_value=False):
            record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=str(uuid4()))
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert spend.accounting_pending and not spend.accounting_failed
        assert spend.finalized_at is None
        self.flag_mock.return_value = False
        create_completed_task_sandbox_session(team_id=self.team.id, task_run_id=run.id, duration=timedelta(seconds=100))
        with (
            patch("products.signals.backend.spend_recovery.recover_spend.apply_async") as dispatch,
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
            patch("products.signals.backend.spend_recovery.submit_signal_metadata_updates", new_callable=AsyncMock),
        ):
            recover_incomplete_spend()
            if funding == "operator":
                dispatch.assert_not_called()
                recover_spend(self.team.id, str(spend.id))
                spend.refresh_from_db()
                assert spend.finalized_at is None
                assert spend.billing_exempt
                return
            dispatch.assert_called_once()
            args = dispatch.call_args.kwargs["args"]
            recover_spend(*args)
            recover_spend(*args)
        with locked_task_run_spend(team_id=self.team.id, run_id=run.id) as cost:
            assert cost.compute_cost_microusd > 0
            expected = 200_001 + 40_000 + cost.compute_cost_microusd
        spend = SignalSpend.objects.for_team(self.team.id).get(id=spend.id)
        assert spend.spend == Decimal(expected) / 10_000
        assert spend.billing_exempt is (funding != "paid")
        assert spend.finalized_at is not None
        assert not spend.accounting_pending and not spend.accounting_failed
        assert trial_usage(grant).settled_microusd == (expected if funding == "trial" else 0)

    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
    def test_unknown_request_id_stays_pending_without_guessing_cost(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            team_id=self.team.id,
            signal_id=signal_id,
            stage="grouping",
            token_cost_microusd=None,
            source_id="unknown-request",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        with patch("products.signals.backend.spend_recovery.fetch_gateway_cost", new_callable=AsyncMock) as fetch:
            recover_spend(self.team.id, str(spend.id))
        fetch.assert_not_awaited()
        spend.refresh_from_db()
        grant.refresh_from_db()
        assert spend.accounting_pending and not spend.accounting_failed
        assert spend.finalized_at is None
        assert spend.accounting_pending
        assert trial_usage(grant).settled_microusd == 0

    def test_permanent_failure_is_not_treated_as_recoverable(self) -> None:
        spend = SignalSpend.objects.create(
            team=self.team,
            signal_id=uuid4(),
            kind=SignalSpend.Kind.AD_HOC,
            accounting_failed=True,
            accounting_pending=True,
            pending_requests={"source": {"stage": "grouping", "request_id": "known"}},
        )
        with (
            patch("products.signals.backend.spend_recovery.recover_spend.apply_async") as dispatch,
            patch("products.signals.backend.spend_recovery.fetch_gateway_cost", new_callable=AsyncMock) as fetch,
            patch(
                "products.signals.backend.spend_recovery.submit_signal_metadata_updates", new_callable=AsyncMock
            ) as publish,
        ):
            recover_incomplete_spend()
            recover_spend(self.team.id, str(spend.id))
        dispatch.assert_not_called()
        fetch.assert_not_awaited()
        publish.assert_not_awaited()
        spend.refresh_from_db()
        assert spend.accounting_failed and spend.accounting_pending
        assert spend.finalized_at is None

    @parameterized.expand([("research",), ("repo_selection",)])
    def test_task_recovery_applies_late_report_billing_exemption(self, stage: str) -> None:
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team, title="Report research", origin_product="signal_report", signal_report=report, internal=True
        )
        with patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=False):
            run = task.create_run(extra_state={"ai_stage": stage, "unprocessed_request_ids": ["late"]})
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert not spend.billing_exempt
        TaskRun.objects.filter(id=run.id, team_id=self.team.id).update(status=TaskRun.Status.COMPLETED)
        SignalReport.objects.filter(id=report.id, team_id=self.team.id).update(
            billing_exempt_reason=SignalReport.BillingExemptReason.POSTHOG_SYSTEM
        )
        with (
            patch(
                "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
                new_callable=AsyncMock,
                return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=123),
            ),
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
        ):
            recover_spend(self.team.id, str(spend.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(id=spend.id)
        assert spend.finalized_at is not None
        assert spend.billing_exempt
        assert not spend.accounting_failed

    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
    def test_publication_retries_after_the_final_receipt_settles(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        source_key = str(uuid4())
        record_llm_spend(
            "late",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="grouping",
            token_cost_microusd=None,
            source_id=f"generation:{source_key}",
            trial_grant_id=str(grant.id),
            strict=True,
        )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        response = AsyncMock(status=200)
        response.__aenter__.return_value = response
        response.json.return_value = {
            "request_id": "late",
            "model": "example",
            "provider": "example",
            "cost_usd": "0.000123",
        }
        with (
            patch("aiohttp.ClientSession._request", new_callable=AsyncMock, return_value=response) as fetch,
            patch(
                "products.signals.backend.spend_recovery.submit_signal_metadata_updates",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("Temporal unavailable"), None],
            ) as publish,
        ):
            result = recover_spend.apply(args=(self.team.id, str(spend.id)), throw=False)
        assert result.successful(), result.result
        assert publish.await_count == 2
        fetch.assert_awaited_once()
        assert fetch.call_args.args[1] == "https://gateway.example.com/v1/usage/late"
        grant.refresh_from_db()
        spend.refresh_from_db()
        assert trial_usage(grant).settled_microusd == 123
        assert not spend.accounting_failed
        assert spend.finalized_at is not None

    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
    def test_recovery_rotates_pending_requests_and_settles_once(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        for index in range(RECOVERY_SOURCE_LIMIT + 1):
            record_llm_spend(
                f"request-{index:02}",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="short",
                token_cost_microusd=None,
                source_id=f"source-{index:02}",
                trial_grant_id=str(grant.id),
                strict=True,
            )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        with (
            patch("products.signals.backend.spend_recovery.fetch_gateway_cost", new_callable=AsyncMock) as fetch,
            patch(
                "products.signals.backend.spend_recovery.submit_signal_metadata_updates", new_callable=AsyncMock
            ) as publish,
        ):
            fetch.return_value = None
            recover_spend(self.team.id, str(spend.id))
            assert fetch.call_count == RECOVERY_SOURCE_LIMIT
            publish.assert_not_awaited()
            fetch.reset_mock()
            fetch.return_value = GatewayRequestCost(model="example", provider="example", cost_microusd=123)
            recover_spend(self.team.id, str(spend.id))
            assert fetch.call_args_list[0].args[0] == f"request-{RECOVERY_SOURCE_LIMIT:02}"
            recover_spend(self.team.id, str(spend.id))
            recover_spend(self.team.id, str(spend.id))
            assert publish.await_count == 3
            publish.assert_awaited_with(team_id=self.team.id, signal_ids=[signal_id])
        grant.refresh_from_db()
        spend.refresh_from_db()
        assert trial_usage(grant).settled_microusd == 123 * (RECOVERY_SOURCE_LIMIT + 1)
        assert not spend.accounting_pending
        assert spend.finalized_at is not None

    @parameterized.expand([(True,), (False,)])
    def test_late_child_environment_cost_recovers_against_original_grant(self, terminal: bool) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        report = SignalReport.objects.create(team=child, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=child, title="Child trial", origin_product="signal_report", signal_report=report, internal=True
        )
        run = task.create_run(
            environment=TaskRun.Environment.CLOUD,
            extra_state={"ai_stage": "research", "unprocessed_request_ids": ["late"]},
        )
        run.status = TaskRun.Status.FAILED if terminal else TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        spend = SignalSpend.objects.for_team(child.id).get(task_run_id=run.id)
        with (
            patch(
                "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
                new_callable=AsyncMock,
                return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=20),
            ),
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
            patch("products.signals.backend.spend_recovery.recover_spend.apply_async") as dispatch,
            patch("products.signals.backend.spend_recovery.submit_signal_metadata_updates", new_callable=AsyncMock),
        ):
            recover_incomplete_spend()
            args = next(
                call.kwargs["args"] for call in dispatch.call_args_list if call.kwargs["args"][1] == str(spend.id)
            )
            assert args[0] == self.team.id
            recover_spend(*args)
            recover_spend(*args)
        grant.refresh_from_db()
        usage = trial_usage(grant)
        assert usage.spend_microusd == 40_020
        assert usage.settled_microusd == (40_020 if terminal else 0)
        spend.refresh_from_db()
        assert not spend.accounting_pending
