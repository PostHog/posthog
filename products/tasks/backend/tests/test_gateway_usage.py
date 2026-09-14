from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.tasks.backend.logic.services.gateway_usage import (
    enable_gateway_usage,
    get_task_spend,
    process_pending_gateway_usage,
)
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS
from products.tasks.backend.models import SandboxSession, Task, TaskRun


@override_settings(SANDBOX_AI_GATEWAY_URL="https://gateway.example.com/v1", SANDBOX_AI_GATEWAY_MINT_KEY="phs_test")
class TestGatewayUsage(BaseTest):
    def _run(self, *, task: Task | None = None, status: str = TaskRun.Status.IN_PROGRESS) -> TaskRun:
        task = task or Task.objects.create(team=self.team, title="Usage test", description="")
        run = TaskRun.objects.create(team=self.team, task=task, status=status, environment=TaskRun.Environment.CLOUD)
        enable_gateway_usage(run_id=run.id, team_id=self.team.id)
        return run

    def _report(self, run: TaskRun, ids: list[str], *, complete: bool = False) -> None:
        TaskRun.update_state_atomic(run.id, updates={"gateway_request_ids": ids, "gateway_usage_complete": complete})

    def _receipt(self, request_id: str, cost: str, *, model: str = "model-a") -> Mock:
        return Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "request_id": request_id,
                    "cost_usd": cost,
                    "model": model,
                    "provider": "provider-a",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "settled_at": timezone.now().isoformat(),
                }
            ),
        )

    def _process(self, run: TaskRun, *, limit: int = 20):
        return process_pending_gateway_usage(run_id=run.id, team_id=self.team.id, limit=limit)

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_unique_request_costs_across_models_and_subagents_use_gateway_prices(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["parent-request", "subagent-request", "other-model", "parent-request"])
        get.side_effect = [
            self._receipt("parent-request", "0.005"),
            self._receipt("subagent-request", "0.010001"),
            self._receipt("other-model", "0.000009", model="model-b"),
        ]
        spend = self._process(run)
        assert spend.token_cost == 2
        assert spend.token_status == "current"
        assert get.call_count == 3
        get.reset_mock()
        assert self._process(run).token_cost == 2
        get.assert_not_called()
        run.refresh_from_db()
        receipts = run.state["_spend_accounting"]["receipts"]
        assert receipts["other-model"]["model"] == "model-b"
        assert receipts["subagent-request"]["cost_microusd"] == 10_001
        assert run.state["spend"]["token_cost"] == 2

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_missing_receipt_stays_pending_until_a_later_activity_processes_it(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.CANCELLED)
        self._report(run, ["request-1"], complete=True)
        get.return_value = Mock(status_code=404)
        spend = self._process(run)
        assert spend.token_cost is None
        assert spend.token_status == "partial"
        get.return_value = self._receipt("request-1", "0.015")
        spend = self._process(run)
        assert spend.token_cost == 2
        assert spend.token_status == "final"
        assert spend.is_final is False

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_missing_receipts_do_not_starve_later_request_ids(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["missing", "priced"])
        get.return_value = Mock(status_code=404)
        self._process(run, limit=1)
        get.return_value = self._receipt("priced", "0.10")
        spend = self._process(run, limit=1)
        assert get.call_args.args[0].endswith("/v1/usage/priced")
        assert spend.token_cost == 10
        assert spend.token_status == "partial"

    @parameterized.expand([("0",), ("0.000001",)])
    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_subcent_receipt_is_known_zero_cents_not_missing(self, cost: str, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        self._report(run, ["request-1"], complete=True)
        get.return_value = self._receipt("request-1", cost)
        spend = self._process(run)
        assert spend.token_cost == 0
        assert spend.token_status == "final"

    @parameterized.expand([("negative", "-1"), ("nan", "NaN"), ("float", 0.5), ("exponent", "1e999999")])
    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_invalid_gateway_price_cannot_become_spend(self, _name: str, cost: object, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={"request_id": "request-1", "cost_usd": cost, "settled_at": timezone.now().isoformat()}
            ),
        )
        spend = self._process(run)
        assert spend.token_cost is None
        assert spend.token_status == "partial"

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_reporter_completion_and_resume_do_not_reprice_or_double_count(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        self._report(run, ["old-request"])
        get.return_value = self._receipt("old-request", "0.015")
        assert self._process(run).token_status == "partial"
        self._report(run, ["old-request"], complete=True)
        assert run.get_current_spend().token_status == "final"
        enable_gateway_usage(run_id=run.id, team_id=self.team.id)
        assert run.get_current_spend().token_status == "partial"
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._report(run, ["old-request", "new-request"])
        get.return_value = self._receipt("new-request", "0.005")
        assert self._process(run).token_cost == 2
        assert get.call_count == 2

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_getters_only_read_persisted_usage_and_aggregate_all_runs_before_rounding(self, get: Mock) -> None:
        first = self._run(status=TaskRun.Status.FAILED)
        second = self._run(task=first.task, status=TaskRun.Status.CANCELLED)
        for index, run in enumerate((first, second)):
            request_id = f"request-{index}"
            self._report(run, [request_id], complete=True)
            get.return_value = self._receipt(request_id, "0.005")
            self._process(run)
        get.reset_mock()
        assert first.get_current_spend().token_cost == 0
        assert second.get_current_spend().token_cost == 0
        assert get_task_spend(team_id=self.team.id, task_id=first.task_id).token_cost == 1
        get.assert_not_called()
        self._report(second, ["request-1", "pending"])
        assert get_task_spend(team_id=self.team.id, task_id=first.task_id).token_status == "partial"

    def test_disabled_and_unfinished_empty_runs_are_not_final_zero(self) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        assert run.get_current_spend().token_cost is None
        self._report(run, [], complete=True)
        assert run.get_current_spend().token_cost == 0
        assert run.get_current_spend().token_status == "final"
        run.state = {}
        run.save(update_fields=["state"])
        assert run.get_current_spend().token_status == "unavailable"

    def test_compute_uses_ledger_attribution_and_preserves_closed_session_rates(self) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        now = timezone.now()
        for name, attributed in (("prewarm", None), ("claimed", now - timedelta(hours=1))):
            SandboxSession.objects.for_team(self.team.id).create(
                team=self.team,
                task_run=run,
                sandbox_id=name,
                cpu_cores=4,
                memory_gb=8,
                cpu_request_cores=1,
                memory_request_mb=1024,
                ttl_seconds=7200,
                created_at=now - timedelta(hours=2),
                ttl_expires_at=now + timedelta(hours=1),
                user_attributed_at=attributed,
                ended_at=now,
            )
        self._report(run, [], complete=True)
        spend = run.get_current_spend()
        card = COMPUTE_RATE_CARDS[-1]
        expected = int(((card.cpu_core_second_usd + card.memory_gib_second_usd) * 3600 * 100).quantize(Decimal(1)))
        assert spend.compute_cost == expected
        assert spend.is_final
        with patch(
            "products.tasks.backend.logic.services.gateway_usage.COMPUTE_RATE_CARDS",
            tuple(replace(c, cpu_core_second_usd=Decimal(1)) for c in COMPUTE_RATE_CARDS),
        ):
            assert run.get_current_spend().compute_cost == spend.compute_cost
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        enable_gateway_usage(run_id=run.id, team_id=self.team.id)
        assert run.get_current_spend().compute_status == "current"
