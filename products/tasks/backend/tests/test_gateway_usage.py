from datetime import timedelta
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from django.test import override_settings
from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.tasks.backend.constants import COMPUTE_WAIVED_REASON_STATE_KEY
from products.tasks.backend.facade.billing import TaskRunCost, get_task_cost, get_task_run_billing, get_task_run_cost
from products.tasks.backend.logic.services.gateway_usage import (
    process_pending_gateway_usage,
    record_gateway_routing,
    record_generation_request,
    refresh_task_run_cost,
)
from products.tasks.backend.logic.services.sandbox_pricing import CLOUD_AGENTS_RATE_CARD, COMPUTE_RATE_CARDS
from products.tasks.backend.logic.services.sandbox_usage import waive_run_sandbox_sessions
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun


@override_settings(SANDBOX_AI_GATEWAY_URL="https://gateway.example.com/v1", SANDBOX_AI_GATEWAY_MINT_KEY="phs_test")
class TestGatewayUsage(BaseTest):
    def _run(self, *, task: Task | None = None, status: str = TaskRun.Status.IN_PROGRESS) -> TaskRun:
        task = task or Task.objects.create(team=self.team, title="Cost test", description="")
        run = TaskRun.objects.create(team=self.team, task=task, status=status, environment=TaskRun.Environment.CLOUD)
        record_gateway_routing(run_id=run.id, team_id=self.team.id, uses_gateway=True)
        return run

    def _report(self, run: TaskRun, ids: list[str]) -> None:
        TaskRun.update_state_atomic(run.id, updates={"unprocessed_request_ids": ids})

    def _response(
        self, request_id: str, cost: object, *, model: str = "model-a", provider: str = "provider-a", status: int = 200
    ) -> MagicMock:
        response = MagicMock(
            status=status,
            json=AsyncMock(
                return_value={
                    "request_id": request_id,
                    "cost_usd": cost,
                    "model": model,
                    "provider": provider,
                }
            ),
        )
        response.__aenter__.return_value = response
        return response

    def _process(self, run: TaskRun, *, limit: int = 20) -> TaskRunCost:
        return process_pending_gateway_usage(run_id=run.id, team_id=self.team.id, limit=limit)

    @patch("aiohttp.ClientSession._request")
    def test_records_cost_by_model_and_provider_and_removes_processed_ids(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["parent", "subagent", "other-model", "second-turn", "parent"])
        get.side_effect = [
            self._response("parent", "0.005"),
            self._response("subagent", "0.010001", provider="provider-b"),
            self._response("other-model", "0.000009", model="model-b"),
            self._response("second-turn", "0.005"),
        ]
        assert self._process(run).token_cost == 2
        assert get.call_count == 4
        assert get.call_args.kwargs["timeout"].total == 15
        run.refresh_from_db()
        assert run.state == {
            "unprocessed_request_ids": [],
            "token_cost": {
                "model-a": {
                    "provider-a": {"cost_microusd": 10_000, "request_ids": ["parent", "second-turn"]},
                    "provider-b": {"cost_microusd": 10_001, "request_ids": ["subagent"]},
                },
                "model-b": {"provider-a": {"cost_microusd": 9, "request_ids": ["other-model"]}},
            },
            "compute_cost": None,
        }
        get.reset_mock()
        assert self._process(run).token_cost == 2
        get.assert_not_called()

    @patch("aiohttp.ClientSession._request")
    def test_overlapping_worker_pass_preserves_new_ids_and_adds_cost_once(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        response = self._response("request-1", "0.015")

        async def other_worker(*_args: object, **_kwargs: object) -> MagicMock:
            get.side_effect = None
            get.return_value = response
            await sync_to_async(self._process)(run)
            await sync_to_async(self._report)(run, ["request-2"])
            return response

        get.side_effect = other_worker
        assert self._process(run).token_cost is None
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-2"]
        assert run.state["token_cost"]["model-a"]["provider-a"] == {
            "cost_microusd": 15_000,
            "request_ids": ["request-1"],
        }

    @parameterized.expand([("unsettled",), ("connection_timeout",), ("body_timeout",)])
    @patch("aiohttp.ClientSession._request")
    def test_unavailable_cost_stays_queued_until_a_later_pass(self, failure: str, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.CANCELLED)
        self._report(run, ["request-1"])
        get.return_value = self._response("request-1", "0", status=404)
        if failure == "connection_timeout":
            get.side_effect = TimeoutError
        elif failure == "body_timeout":
            get.return_value.status = 200
            get.return_value.json.side_effect = TimeoutError
        assert self._process(run).token_cost is None
        assert get_task_cost(team_id=self.team.id, task_id=run.task_id).token_cost is None
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-1"]
        assert run.state["token_cost"] == {}
        get.side_effect = None
        get.return_value = self._response("request-1", "0.015")
        assert self._process(run).token_cost == 2
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []

    @patch("aiohttp.ClientSession._request")
    def test_missing_responses_rotate_behind_other_pending_ids(self, get: Mock) -> None:
        run = self._run()
        self._report(run, ["missing", "priced"])
        get.return_value = self._response("missing", "0", status=404)
        self._process(run, limit=1)
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["priced", "missing"]
        get.return_value = self._response("priced", "0.10")
        assert self._process(run, limit=1).token_cost is None
        assert get_task_run_cost(run_id=run.id, team_id=self.team.id).token_cost is None
        assert get_task_cost(team_id=self.team.id, task_id=run.task_id).token_cost is None
        assert get.call_args.args[1].endswith("/v1/usage/priced")
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["missing"]

    @parameterized.expand([("0",), ("0.000001",)])
    @patch("aiohttp.ClientSession._request")
    def test_subcent_cost_is_processed_without_losing_precision(self, cost: str, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        get.return_value = self._response("request-1", cost)
        assert self._process(run).token_cost == 0
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []
        assert run.state["token_cost"]["model-a"]["provider-a"]["cost_microusd"] == int(Decimal(cost) * 1_000_000)

    @parameterized.expand([("negative", "-1"), ("nan", "NaN"), ("float", 0.5), ("exponent", "1e999999")])
    @patch("aiohttp.ClientSession._request")
    def test_invalid_gateway_cost_stays_queued(self, _name: str, cost: object, get: Mock) -> None:
        run = self._run()
        self._report(run, ["request-1"])
        get.return_value = self._response("request-1", cost)
        assert self._process(run).token_cost is None
        assert get_task_cost(team_id=self.team.id, task_id=run.task_id).token_cost is None
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request-1"]
        assert run.state["token_cost"] == {}

    @parameterized.expand([(True,), (False,)])
    @patch("aiohttp.ClientSession._request")
    def test_resume_preserves_pending_ids_and_processed_cost(self, fully_tracked: bool, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        self._report(run, ["old-request", "pending"])
        get.return_value = self._response("old-request", "0.015")
        self._process(run, limit=1)
        if not fully_tracked:
            record_gateway_routing(run_id=run.id, team_id=self.team.id, uses_gateway=False)
        record_gateway_routing(run_id=run.id, team_id=self.team.id, uses_gateway=True)
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["pending"]
        expected_cost = 2 if fully_tracked else None
        assert get_task_run_cost(run_id=run.id, team_id=self.team.id).token_cost is None
        assert get_task_cost(team_id=self.team.id, task_id=run.task_id).token_cost is None
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        self._report(run, ["old-request", "pending"])
        get.side_effect = [self._response("old-request", "0.015"), self._response("pending", "0.005")]
        assert self._process(run).token_cost == expected_cost
        run.refresh_from_db()
        assert run.state["token_cost"]["model-a"]["provider-a"]["request_ids"] == ["old-request", "pending"]
        assert run.state["token_cost"]["model-a"]["provider-a"]["cost_microusd"] == 20_000

    @patch("aiohttp.ClientSession._request")
    def test_getters_use_recorded_cost_and_round_across_runs(self, get: Mock) -> None:
        first = self._run(status=TaskRun.Status.FAILED)
        second = self._run(task=first.task, status=TaskRun.Status.CANCELLED)
        now = timezone.now()
        for index, run in enumerate((first, second)):
            SandboxSession.objects.for_team(self.team.id).create(
                team=self.team,
                task_run=run,
                sandbox_id=f"sandbox-{index}",
                cpu_cores=2,
                memory_gb=4,
                ttl_seconds=600,
                created_at=now - timedelta(seconds=20),
                ttl_expires_at=now + timedelta(minutes=5),
                user_attributed_at=now - timedelta(seconds=20),
                ended_at=now,
            )
            request_id = f"request-{index}"
            self._report(run, [request_id])
            get.return_value = self._response(request_id, "0.005")
            self._process(run)
        get.reset_mock()
        assert get_task_run_cost(run_id=first.id, team_id=self.team.id) == TaskRunCost(token_cost=0, compute_cost=0)
        assert get_task_run_cost(run_id=second.id, team_id=self.team.id) == TaskRunCost(token_cost=0, compute_cost=0)
        with self.assertNumQueries(3):
            assert get_task_cost(team_id=self.team.id, task_id=first.task_id) == TaskRunCost(
                token_cost=1, compute_cost=1
            )
        get.assert_not_called()

    def test_untracked_runs_have_no_recorded_token_cost(self) -> None:
        run = self._run()
        assert get_task_run_cost(run_id=run.id, team_id=self.team.id).token_cost == 0
        run.state = {}
        run.save(update_fields=["state"])
        assert get_task_run_cost(run_id=run.id, team_id=self.team.id).token_cost is None

    def test_compute_cost_uses_existing_ledger_attribution_and_resource_floors(self) -> None:
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
        cost = get_task_run_cost(run_id=run.id, team_id=self.team.id)
        card = COMPUTE_RATE_CARDS[-1]
        expected = int(((card.cpu_core_second_usd + card.memory_gib_second_usd) * 3600 * 100).quantize(Decimal(1)))
        assert cost.compute_cost == expected
        assert get_task_cost(team_id=self.team.id, task_id=run.task_id) == cost
        run.refresh_from_db()
        assert "compute_cost" not in run.state
        assert refresh_task_run_cost(run_id=run.id, team_id=self.team.id) == cost
        run.refresh_from_db()
        assert run.state["compute_cost"] == expected
        assert set(run.state) == {"unprocessed_request_ids", "token_cost", "compute_cost"}

    def _cloud_agents_task(self, *, billed: bool = True) -> Task:
        return Task.objects.create(
            team=self.team,
            title="Cloud agent",
            description="",
            origin_product=Task.OriginProduct.CLOUD_AGENTS,
            client_provenance=TaskClientProvenance.CLOUD_AGENTS if billed else None,
            internal=True,
        )

    def _hour_session(
        self, run: TaskRun, sandbox_id: str, *, closed: bool = True, **overrides: object
    ) -> SandboxSession:
        # One hour of a 4 vCPU and 16 GiB box is $0.368 at the Cloud Agents price.
        start = timezone.now() - timedelta(hours=3)
        return SandboxSession.objects.for_team(self.team.id).create(
            **{
                "team": self.team,
                "task_run": run,
                "sandbox_id": sandbox_id,
                "origin_product": run.task.origin_product,
                "client_provenance": run.task.client_provenance,
                "cpu_cores": 4,
                "memory_gb": 16,
                "ttl_seconds": 6 * 3600,
                "created_at": start,
                "ttl_expires_at": start + timedelta(hours=6),
                "user_attributed_at": start,
                "ended_at": start + timedelta(hours=1) if closed else None,
                **overrides,
            }
        )

    def test_cloud_agents_task_cost_sums_every_run_at_the_box_size(self) -> None:
        task = self._cloud_agents_task()
        first = self._run(task=task, status=TaskRun.Status.COMPLETED)
        resumed = self._run(task=task, status=TaskRun.Status.COMPLETED)
        # A burstable floor is recorded on the first session and must not lower its price.
        self._hour_session(first, "first", burstable=True, cpu_request_cores=0.5, memory_request_mb=1024)
        self._hour_session(resumed, "resumed")

        assert get_task_run_cost(run_id=first.id, team_id=self.team.id).compute_cost == 37
        assert refresh_task_run_cost(run_id=resumed.id, team_id=self.team.id).compute_cost == 37
        assert get_task_cost(team_id=self.team.id, task_id=task.id).compute_cost == 74

        billing = get_task_run_billing(team_id=self.team.id, task_id=task.id)
        assert billing.compute_cost_cents == 74
        assert billing.inference_cost_cents == 0
        assert (billing.vcpu_seconds, billing.gib_seconds) == (Decimal(28_800), Decimal(115_200))
        assert (billing.billable, billing.waived, billing.settled) == (True, False, True)
        assert billing.inference_billing == "posthog"
        assert billing.rate_card_version == CLOUD_AGENTS_RATE_CARD.version
        assert [(s.cpu_cores, s.memory_gb, s.seconds, s.cost_cents, s.waived) for s in billing.sessions] == [
            (4, 16, 3600, 37, False)
        ] * 2

    def test_waived_cloud_agents_run_costs_nothing(self) -> None:
        task = self._cloud_agents_task()
        failed = self._run(task=task, status=TaskRun.Status.FAILED)
        resumed = self._run(task=task, status=TaskRun.Status.COMPLETED)
        self._hour_session(failed, "failed")
        self._hour_session(resumed, "resumed")
        waive_run_sandbox_sessions(failed.id, self.team.id, "SandboxProvisionError")

        assert get_task_run_cost(run_id=failed.id, team_id=self.team.id).compute_cost == 0
        assert refresh_task_run_cost(run_id=failed.id, team_id=self.team.id).compute_cost == 0
        assert get_task_cost(team_id=self.team.id, task_id=task.id).compute_cost == 37
        billing = get_task_run_billing(team_id=self.team.id, task_id=task.id)
        assert billing.compute_cost_cents == 37
        assert billing.waived is True
        assert (billing.vcpu_seconds, billing.gib_seconds) == (Decimal(14_400), Decimal(57_600))
        assert [(s.cost_cents, s.waived) for s in billing.sessions] == [(0, True), (37, False)]

    def test_waiver_never_changes_the_cost_of_another_product(self) -> None:
        run = self._run(status=TaskRun.Status.FAILED)
        self._hour_session(run, "desktop")
        before = get_task_run_cost(run_id=run.id, team_id=self.team.id)
        assert waive_run_sandbox_sessions(run.id, self.team.id, "SandboxProvisionError") is False
        TaskRun.update_state_atomic(run.id, updates={COMPUTE_WAIVED_REASON_STATE_KEY: "SandboxProvisionError"})

        assert before.compute_cost
        assert get_task_run_cost(run_id=run.id, team_id=self.team.id) == before
        assert get_task_run_billing(team_id=self.team.id, task_id=run.task_id).waived is False

    @parameterized.expand(
        [
            ("open_session", False, [], TaskRun.Status.COMPLETED, False),
            ("pending_gateway_usage", True, ["request-1"], TaskRun.Status.COMPLETED, False),
            ("active_run", True, [], TaskRun.Status.IN_PROGRESS, False),
            ("all_closed", True, [], TaskRun.Status.COMPLETED, True),
        ]
    )
    def test_billing_is_settled_only_when_nothing_can_change(
        self, _name: str, closed: bool, pending: list[str], status: str, settled: bool
    ) -> None:
        run = self._run(task=self._cloud_agents_task(), status=status)
        self._hour_session(run, "sandbox", closed=closed)
        self._report(run, pending)

        billing = get_task_run_billing(team_id=self.team.id, task_id=run.task_id)

        assert billing.settled is settled
        assert (billing.inference_cost_cents is None) is bool(pending)

    def test_unbilled_internal_cloud_agents_run_reports_its_compute_at_the_cloud_agents_price(self) -> None:
        run = self._run(task=self._cloud_agents_task(billed=False), status=TaskRun.Status.COMPLETED)
        self._hour_session(run, "internal")

        billing = get_task_run_billing(team_id=self.team.id, task_id=run.task_id)

        assert billing.billable is False
        assert billing.compute_cost_cents == 37
        assert billing.rate_card_version == CLOUD_AGENTS_RATE_CARD.version

    @parameterized.expand(
        [
            ("claude_subscription", {"claude_model_access": "own-subscription"}),
            ("chatgpt_subscription", {"runtime_adapter": "codex", "codex_model_access": "own-subscription"}),
        ]
    )
    def test_inference_on_the_owners_subscription_has_no_inference_cost(
        self, _name: str, state: dict[str, str]
    ) -> None:
        run = self._run(task=self._cloud_agents_task(), status=TaskRun.Status.COMPLETED)
        TaskRun.update_state_atomic(run.id, updates=state)
        self._hour_session(run, "own")

        billing = get_task_run_billing(team_id=self.team.id, task_id=run.task_id)

        assert billing.inference_billing == "own_subscription"
        assert billing.inference_cost_cents is None
        assert billing.compute_cost_cents == 37

    @patch("aiohttp.ClientSession._request")
    def test_accounting_after_completion_has_no_completion_side_effects(self, get: Mock) -> None:
        run = self._run(status=TaskRun.Status.COMPLETED)
        Task.objects.filter(id=run.task_id).update(json_schema={"type": "object"})
        TaskRun.objects.filter(id=run.id).update(output={"result": "done"})
        run.refresh_from_db()
        completed_updated_at = run.updated_at
        get.return_value = self._response("late-request", "0.02")

        with patch.object(TaskRun, "track_structured_result") as track_result:
            record_gateway_routing(run_id=run.id, team_id=run.team_id, uses_gateway=True)
            record_generation_request(run_id=run.id, team_id=run.team_id, request_id="late-request")
            assert self._process(run).token_cost == 2
            assert get_task_run_cost(run_id=run.id, team_id=self.team.id).token_cost == 2
            track_result.assert_not_called()
        run.refresh_from_db()
        assert run.updated_at == completed_updated_at
