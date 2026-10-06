import json
import asyncio
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import httpx
from anthropic import APIResponseValidationError, AsyncAnthropic
from fakeredis import FakeRedis
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.token_bucket import TEST_reset_scripts

from products.ml_inference.backend.facade.contracts import DecisionGatewayError, DecisionResult, NoulAnswer
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync
from products.signals.backend.spend import record_llm_request, signal_spend_summaries, signal_spend_totals
from products.signals.backend.spend_tasks import reconcile_signal_spend
from products.signals.backend.system_one_decision import SignalsDecisionError, run_model_decision
from products.signals.backend.system_one_prompts import bundled_prompt
from products.signals.backend.temporal.llm import call_llm
from products.tasks.backend.facade.task_run_signals import task_run_cost_updated
from products.tasks.backend.models import Task, TaskRun


class TestSpendPricing(SimpleTestCase):
    @parameterized.expand([(1, 0, "0.0001"), (10_001, 1, "5.0001"), (0, 1, "4"), (123_456, 2, "20.3456")])
    def test_price_in_cents(self, cost: int, tasks: int, expected: str) -> None:
        assert cost_to_spend(cost, task_count=tasks) == Decimal(expected)


class TestSignalSpend(BaseTest):
    @parameterized.expand([("invalid_json",), ("invalid_message",)])
    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="phs_test")
    async def test_unreadable_generation_preserves_request_id_or_records_failed_stage(self, failure: str) -> None:
        driver = str(uuid4())
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "x-request-id": "generation-1",
                    "request-id": "generation-1",
                    "content-type": "application/json",
                },
                content=b"not-json" if failure == "invalid_json" else b"{}",
            )
        )
        async with AsyncAnthropic(
            api_key="test-key",
            http_client=httpx.AsyncClient(transport=transport),
            _strict_response_validation=True,
        ) as client:
            with (
                patch("products.signals.backend.temporal.llm.build_async_anthropic_client", return_value=client),
                self.assertRaises(json.JSONDecodeError if failure == "invalid_json" else APIResponseValidationError),
            ):
                await call_llm(
                    team_id=self.team.id,
                    signal_id=driver,
                    system_prompt="Example prompt",
                    user_prompt="Example finding",
                    validate=lambda text: text,
                    stage="safety",
                    ai_product="signals",
                )
        spend = await database_sync_to_async(lambda: SignalSpend.objects.for_team(self.team.id).get(signal_id=driver))()
        assert spend.stage == "safety"
        assert spend.accounting_failed is (failure == "invalid_json")
        if failure == "invalid_json":
            assert spend.source_id.startswith("unknown-")
        else:
            assert spend.source_id == "generation-1"

    @parameterized.expand([("gateway",), ("missing_request_id",), ("legacy",)])
    async def test_parallel_generations_record_every_attempt_for_the_explicit_owner(self, mode: str) -> None:
        drivers = [str(uuid4()), str(uuid4())]
        attempts: dict[str, int] = {}

        async def respond(request: httpx.Request) -> httpx.Response:
            key = json.loads(request.content)["messages"][0]["content"]
            attempts[key] = attempts.get(key, 0) + 1
            return httpx.Response(
                200,
                headers={"x-request-id": f"{key}-{attempts[key]}", "request-id": f"{key}-{attempts[key]}"}
                if mode != "missing_request_id"
                else {},
                json={
                    "id": "msg_example",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5",
                    "content": [
                        {"type": "text", "text": "invalid" if key == "request-a" and attempts[key] == 1 else "ok"}
                    ],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            )

        def validate(text: str) -> str:
            if text != "ok":
                raise ValueError("Invalid generation")
            return text

        async def call(driver: str | None, request_id: str) -> str:
            return await call_llm(
                team_id=self.team.id,
                signal_id=driver,
                system_prompt="Example prompt",
                user_prompt=request_id,
                validate=validate,
                stage="actionability",
                ai_product="signals",
                model="claude-sonnet-5",
            )

        with (
            override_settings(
                AI_GATEWAY_URL="" if mode == "legacy" else "https://gateway.example.com/v1",
                AI_GATEWAY_API_KEY="" if mode == "legacy" else "phs_test",
                LLM_GATEWAY_URL="https://legacy.example.com",
                LLM_GATEWAY_API_KEY="test-key",
            ),
            patch("httpx.AsyncHTTPTransport.handle_async_request", new=AsyncMock(side_effect=respond)),
        ):
            results = await asyncio.gather(call(drivers[0], "request-a"), call(drivers[1], "request-b"))
            assert list(results) == ["ok", "ok"]
            assert await call(None, "unattributed") == "ok"
        rows = await database_sync_to_async(
            lambda: list(
                SignalSpend.objects.for_team(self.team.id).values(
                    "source_id", "signal_id", "stage", "accounting_failed"
                )
            )
        )()
        assert len(rows) == 3
        assert sorted(str(row["signal_id"]) for row in rows) == sorted([drivers[0], drivers[0], drivers[1]])
        assert all(row["stage"] == "actionability" for row in rows)
        if mode == "gateway":
            assert {row["source_id"]: str(row["signal_id"]) for row in rows} == {
                "request-a-1": drivers[0],
                "request-a-2": drivers[0],
                "request-b-1": drivers[1],
            }
            assert not any(row["accounting_failed"] for row in rows)
        else:
            assert all(row["accounting_failed"] for row in rows)
            assert all(row["source_id"].startswith("unknown-") for row in rows)

    @parameterized.expand([("success",), ("missing_request_id",), ("invalid",), ("refused",)])
    async def test_system_one_records_generation_ids_even_when_validation_fails(self, outcome: str) -> None:
        driver = str(uuid4())
        result = DecisionResult(
            model="jevk5-fp8-0.2",
            answers={"actionable": NoulAnswer(probability=0.98)},
            input_tokens=10,
            request_id=None if outcome == "missing_request_id" else "decision-request",
        )
        failure = (
            DecisionGatewayError(200 if outcome == "invalid" else 429, "Example failure", request_id="decision-request")
            if outcome in {"invalid", "refused"}
            else None
        )
        TEST_reset_scripts()
        try:
            with (
                patch("products.signals.backend.system_one_decision.get_client", return_value=FakeRedis()),
                patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
                patch(
                    "products.signals.backend.system_one_decision.decision_api.decide_when_available",
                    return_value=result,
                    side_effect=failure,
                ),
            ):
                call = run_model_decision(
                    team_id=self.team.id,
                    signal_id=driver,
                    stage="actionability",
                    primary_model="claude-sonnet-5",
                    source_id="issue-1",
                    source_product="linear",
                    state={"record": "An example finding"},
                    prompt=bundled_prompt("example-prompt", "policy", "Actionable?", 0.9),
                    traditional=AsyncMock(return_value=False),
                    verdict=lambda value: value,
                    system_one_result=lambda value, _category: value,
                    mode_override="system-one-only",
                )
                if failure:
                    with self.assertRaises(SignalsDecisionError):
                        await call
                else:
                    assert await call is True
        finally:
            TEST_reset_scripts()
        rows = await database_sync_to_async(
            lambda: list(
                SignalSpend.objects.for_team(self.team.id).values(
                    "source_id", "signal_id", "stage", "accounting_failed"
                )
            )
        )()
        if outcome == "refused":
            assert rows == []
        else:
            assert len(rows) == 1
            assert str(rows[0]["signal_id"]) == driver
            assert rows[0]["stage"] == "actionability"
            assert rows[0]["accounting_failed"] is (outcome == "missing_request_id")
            if outcome != "missing_request_id":
                assert rows[0]["source_id"] == "decision-request"

    def _run(self, *, report: SignalReport | None = None, task: Task | None = None, stage: str = "research") -> TaskRun:
        task = task or Task.objects.create(
            team=self.team,
            title="Example research",
            description="",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report=report,
        )
        return TaskRun.objects.create(
            team=self.team,
            task=task,
            environment=TaskRun.Environment.CLOUD,
            status=TaskRun.Status.IN_PROGRESS,
            state={"ai_stage": stage, "unprocessed_request_ids": [], "token_cost": {}},
        )

    def _set_task_cost(self, run: TaskRun, cost: int | None) -> None:
        run.refresh_from_db()
        state = dict(run.state or {})
        state["unprocessed_request_ids"] = ["pending-request"] if cost is None else []
        if cost is not None:
            state["token_cost"] = {"model-a": {"provider-a": {"cost_microusd": cost}}}
        run.state = state
        run.save(update_fields=["state"])
        task_run_cost_updated.send(sender=TaskRun, run_id=run.id, team_id=self.team.id)

    def test_late_task_cost_updates_charge_driver_once_and_preserve_fractional_cents(self) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        research = self._run(report=report)
        implementation = self._run(report=report, stage="implementation")
        self._set_task_cost(research, 10_001)
        self._set_task_cost(implementation, 25_002)
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5003}

        report.triggering_signal_id = other
        report.save(update_fields=["triggering_signal_id"])
        self._set_task_cost(research, 10_004)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 11.5003}
        reconcile_signal_spend()
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5006}
        assert SignalSpend.objects.for_team(self.team.id).count() == 2

        rerun = self._run(task=implementation.task, stage="implementation")
        self._set_task_cost(rerun, 1)
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 15.5007}

    @parameterized.expand([(None,), (RuntimeError("usage lookup failed"),)])
    def test_one_shot_requests_preserve_known_spend_and_record_failed_stage(self, failure: Exception | None) -> None:
        driver = str(uuid4())
        for request_id in ["one-shot-1", "one-shot-2", "one-shot-1"]:
            record_llm_request(request_id, team_id=self.team.id, signal_id=driver, stage="actionability")
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 0}
        with patch(
            "products.signals.backend.spend_tasks.fetch_gateway_cost",
            new=AsyncMock(
                side_effect=[failure, GatewayRequestCost(model="model-a", provider="provider-a", cost_microusd=9)]
            ),
        ):
            reconcile_signal_spend()
        summary = signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver]
        assert summary.total_spend == 0.0009
        assert summary.failed_stages == ["actionability"]
        with patch(
            "products.signals.backend.spend_tasks.fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="model-a", provider="provider-a", cost_microusd=1)),
        ):
            reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 0.001}
        assert signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver].failed_stages == []
        record_llm_request(None, team_id=self.team.id, signal_id=driver, stage="summarization")
        now = timezone.now()
        with patch(
            "products.signals.backend.signal_metadata.execute_hogql_query",
            return_value=Mock(results=[(driver, "Example finding", json.dumps({"total_spend": 0}), now, now)]),
        ):
            signal = fetch_signals_for_report_sync(self.team, str(uuid4()))[0]
            assert signal["total_spend"] == 0.001
            assert signal["spend_accounting_failed_stages"] == ["summarization"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        assert signal_spend_totals(team_id=other_team.id, signal_ids=[driver]) == {}

    def test_scout_persists_spend_in_cents_after_failed_run_settles(self) -> None:
        task_run = self._run()
        scout = SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=task_run,
            skill_name="example-scout",
            skill_version=1,
        )
        task_run.status = TaskRun.Status.FAILED
        task_run.save(update_fields=["status"])
        self._set_task_cost(task_run, 123_456)
        reconcile_signal_spend()
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        self._set_task_cost(task_run, None)
        reconcile_signal_spend()
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == ["scout"]
        self._set_task_cost(task_run, 123_457)
        reconcile_signal_spend()
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3457")
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == []

    @parameterized.expand([("generation",), ("task",)])
    def test_accounting_database_failure_does_not_abort_pipeline_transaction(self, source: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)

        def fail_spend_insert(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith('INSERT INTO "signals_signalspend"'):
                return execute("SELECT 1 / 0", (), False, context)
            return execute(sql, params, many, context)

        with capture_logs() as logs, connection.execute_wrapper(fail_spend_insert):
            if source == "task":
                run = self._run(report=report)
                assert TaskRun.objects.filter(id=run.id).exists()
            else:
                record_llm_request("example-request", team_id=self.team.id, signal_id=driver, stage="actionability")
        assert SignalReport.objects.filter(id=report.id).exists()
        assert any(
            log["event"] == "signals.spend.accounting_failed"
            and log["stage"] == ("research" if source == "task" else "actionability")
            for log in logs
        )
