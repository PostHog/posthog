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
    record_generation_request,
)
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS
from products.tasks.backend.models import SandboxSession, Task, TaskRun


@override_settings(SANDBOX_AI_GATEWAY_URL="https://gateway.example.com/v1", SANDBOX_AI_GATEWAY_MINT_KEY="phs_test")
class TestGatewayUsage(BaseTest):
    def _run(self, *, task: Task | None = None, status: str = TaskRun.Status.IN_PROGRESS) -> TaskRun:
        task = task or Task.objects.create(team=self.team, title="Spend test", description="")
        run = TaskRun.objects.create(team=self.team, task=task, status=status, environment=TaskRun.Environment.CLOUD)
        enable_gateway_usage(run_id=run.id, team_id=self.team.id)
        return run

    def _report(self, run: TaskRun, ids: list[str]) -> None:
        TaskRun.update_state_atomic(run.id, updates={"unprocessed_request_ids": ids})

    def _response(self, request_id: str, spend: str, *, model: str = "model-a", provider: str = "provider-a") -> Mock:
        return Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "request_id": request_id,
                    "cost_usd": spend,
                    "model": model,
                    "provider": provider,
                }
            ),
        )

    def _process(self, run: TaskRun, *, limit: int = 20):
        return process_pending_gateway_usage(run_id=run.id, team_id=self.team.id, limit=limit)

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_records_spend_by_model_and_provider_and_removes_processed_ids(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["parent", "subagent", "other-model", "second-turn", "parent"])
        get.side_effect = [
            self._response("parent", "0.005"),
            self._response("subagent", "0.010001", provider="provider-b"),
            self._response("other-model", "0.000009", model="model-b"),
            self._response("second-turn", "0.005"),
        ]
        assert self._process(run).token_spend == 2
        assert get.call_count == 4
        run.refresh_from_db()
        assert run.state == {
            "unprocessed_request_ids": [],
            "token_spend": {
                "model-a": {
                    "provider-a": {"spend_microusd": 10_000, "request_ids": ["parent", "second-turn"]},
                    "provider-b": {"spend_microusd": 10_001, "request_ids": ["subagent"]},
                },
                "model-b": {"provider-a": {"spend_microusd": 9, "request_ids": ["other-model"]}},
            },
            "compute_spend": None,
        }
        get.reset_mock()
        assert self._process(run).token_spend == 2
        get.assert_not_called()

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_overlapping_worker_pass_preserves_new_ids_and_adds_spend_once(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        response = self._response("request-1", "0.015")

        def other_worker(*_args, **_kwargs):
            get.side_effect = None
            get.return_value = response
            self._process(run)
            self._report(run, ["request-2"])
            return response

        get.side_effect = other_worker
        assert self._process(run).token_spend == 2
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-2"]
        assert run.state["token_spend"]["model-a"]["provider-a"] == {
            "spend_microusd": 15_000,
            "request_ids": ["request-1"],
        }

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_unavailable_spend_stays_queued_until_a_later_pass(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.CANCELLED)
        self._report(run, ["request-1"])
        get.return_value = Mock(status_code=404)
        assert self._process(run).token_spend == 0
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-1"]
        assert run.state["token_spend"] == {}
        get.return_value = self._response("request-1", "0.015")
        assert self._process(run).token_spend == 2
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_missing_responses_rotate_behind_other_pending_ids(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["missing", "priced"])
        get.return_value = Mock(status_code=404)
        self._process(run, limit=1)
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["priced", "missing"]
        get.return_value = self._response("priced", "0.10")
        assert self._process(run, limit=1).token_spend == 10
        assert get.call_args.args[0].endswith("/v1/usage/priced")
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["missing"]

    @parameterized.expand([("0",), ("0.000001",)])
    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_subcent_spend_is_processed_without_losing_precision(self, spend: str, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        get.return_value = self._response("request-1", spend)
        assert self._process(run).token_spend == 0
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []
        assert run.state["token_spend"]["model-a"]["provider-a"]["spend_microusd"] == int(Decimal(spend) * 1_000_000)

    @parameterized.expand([("negative", "-1"), ("nan", "NaN"), ("float", 0.5), ("exponent", "1e999999")])
    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_invalid_gateway_spend_stays_queued(self, _name: str, spend: object, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        get.return_value = Mock(status_code=200, json=Mock(return_value={"request_id": "request-1", "cost_usd": spend}))
        assert self._process(run).token_spend == 0
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-1"]
        assert run.state["token_spend"] == {}

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_resume_preserves_pending_ids_and_processed_spend(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        self._report(run, ["old-request", "pending"])
        get.return_value = self._response("old-request", "0.015")
        self._process(run, limit=1)
        enable_gateway_usage(run_id=run.id, team_id=self.team.id)
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["pending"]
        assert run.get_current_spend().token_spend == 2
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._report(run, ["old-request", "pending"])
        get.side_effect = [self._response("old-request", "0.015"), self._response("pending", "0.005")]
        assert self._process(run).token_spend == 2
        run.refresh_from_db()
        assert run.state["token_spend"]["model-a"]["provider-a"]["request_ids"] == ["old-request", "pending"]

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_getters_use_recorded_spend_and_round_across_runs(self, get: Mock) -> None:
        first = self._run(status=TaskRun.Status.FAILED)
        second = self._run(task=first.task, status=TaskRun.Status.CANCELLED)
        for index, run in enumerate((first, second)):
            request_id = f"request-{index}"
            self._report(run, [request_id])
            get.return_value = self._response(request_id, "0.005")
            self._process(run)
        get.reset_mock()
        assert first.get_current_spend().token_spend == 0
        assert second.get_current_spend().token_spend == 0
        assert get_task_spend(team_id=self.team.id, task_id=first.task_id).token_spend == 1
        get.assert_not_called()

    def test_untracked_runs_have_no_recorded_token_spend(self) -> None:
        run = self._run()
        assert run.get_current_spend().token_spend == 0
        run.state = {}
        run.save(update_fields=["state"])
        assert run.get_current_spend().token_spend is None

    def test_compute_spend_uses_existing_ledger_attribution_and_resource_floors(self) -> None:
        run = self._run()
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
        spend = run.get_current_spend()
        card = COMPUTE_RATE_CARDS[-1]
        expected = int(((card.cpu_core_second_usd + card.memory_gib_second_usd) * 3600 * 100).quantize(Decimal(1)))
        assert spend.compute_spend == expected
        run.refresh_from_db()
        assert run.state["compute_spend"] == expected
        assert set(run.state) == {"unprocessed_request_ids", "token_spend", "compute_spend"}

    @patch("products.tasks.backend.logic.services.gateway_usage.requests.get")
    def test_accounting_after_completion_does_not_reemit_structured_results(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        Task.objects.filter(id=run.task_id).update(json_schema={"type": "object"})
        TaskRun.objects.filter(id=run.id).update(output={"result": "done"})
        get.return_value = self._response("late-request", "0.02")

        with patch.object(TaskRun, "track_structured_result") as track_result:
            enable_gateway_usage(run_id=run.id, team_id=run.team_id)
            record_generation_request(run_id=run.id, team_id=run.team_id, request_id="late-request")
            assert self._process(run).token_spend == 2
            assert run.get_current_spend().token_spend == 2
            track_result.assert_not_called()
