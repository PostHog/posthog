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
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.llm.usage import record_gateway_response, record_unpriced_response
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend import signal_spend_scope, signal_spend_summaries, signal_spend_totals
from products.signals.backend.spend_tasks import reconcile_signal_spend
from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync
from products.tasks.backend.logic.services.gateway_usage import process_pending_gateway_usage, record_generation_request
from products.tasks.backend.models import Task, TaskRun


class TestSpendPricing(SimpleTestCase):
    @parameterized.expand([(1, 0, "0.0001"), (10_001, 1, "5.0001"), (0, 1, "4"), (123_456, 2, "20.3456")])
    def test_price_in_cents(self, cost: int, tasks: int, expected: str) -> None:
        assert cost_to_spend(cost, task_count=tasks) == Decimal(expected)


class TestSignalSpend(BaseTest):
    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="phs_test")
    async def test_parallel_gateway_calls_keep_their_signal_owner(self) -> None:
        drivers = [str(uuid4()), str(uuid4())]

        async def respond(request: httpx.Request) -> httpx.Response:
            key = json.loads(request.content)["messages"][0]["content"]
            return httpx.Response(
                200,
                headers={"x-request-id": key},
                json={
                    "id": "msg_example",
                    "type": "message",
                    "role": "assistant",
                    "model": "model-a",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            )

        async def call(driver: str | None, request_id: str) -> None:
            with signal_spend_scope(self.team.id, driver, stage="actionability"):
                await client.messages.create(
                    model="model-a", max_tokens=10, messages=[{"role": "user", "content": request_id}]
                )

        client = build_async_anthropic_client("signals", team_id=self.team.id)
        try:
            with patch("httpx.AsyncHTTPTransport.handle_async_request", new=AsyncMock(side_effect=respond)):
                await asyncio.gather(call(drivers[0], "request-a"), call(drivers[1], "request-b"))
                await call(None, "unattributed")
        finally:
            await client.close()
        rows = await database_sync_to_async(
            lambda: list(SignalSpend.objects.for_team(self.team.id).values_list("source_id", "signal_id"))
        )()
        assert {source: str(owner) for source, owner in rows} == {"request-a": drivers[0], "request-b": drivers[1]}

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

    def _settle(self, run: TaskRun, request_id: str, cost: int) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            record_generation_request(team_id=self.team.id, run_id=run.id, request_id=request_id)
            with patch(
                "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
                new=AsyncMock(
                    return_value=GatewayRequestCost(model="model-a", provider="provider-a", cost_microusd=cost)
                ),
            ):
                process_pending_gateway_usage(team_id=self.team.id, run_id=run.id)

    def test_late_task_cost_updates_charge_driver_once_and_preserve_fractional_cents(self) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        research = self._run(report=report)
        implementation = self._run(report=report, stage="implementation")
        self._settle(research, "research-1", 10_001)
        self._settle(implementation, "implementation-1", 25_002)
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5003}

        report.triggering_signal_id = other
        report.save(update_fields=["triggering_signal_id"])
        self._settle(research, "research-late", 3)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 11.5003}
        reconcile_signal_spend()
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5006}
        assert SignalSpend.objects.for_team(self.team.id).count() == 2

        rerun = self._run(task=implementation.task, stage="implementation")
        self._settle(rerun, "rerun-1", 1)
        reconcile_signal_spend()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 15.5007}

    @parameterized.expand([(None,), (RuntimeError("usage lookup failed"),)])
    def test_one_shot_requests_preserve_known_spend_and_record_failed_stage(self, failure: Exception | None) -> None:
        driver = str(uuid4())
        with signal_spend_scope(self.team.id, driver, stage="actionability"):
            for request_id in ["one-shot-1", "one-shot-2", "one-shot-1"]:
                record_gateway_response(
                    httpx.Response(
                        200,
                        headers={"x-request-id": request_id},
                        request=httpx.Request("POST", "https://gateway.example.com/v1/messages"),
                    )
                )
            record_gateway_response(
                httpx.Response(
                    200,
                    headers={"x-request-id": "token-count"},
                    request=httpx.Request("POST", "https://gateway.example.com/v1/messages/count_tokens"),
                )
            )
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
        with signal_spend_scope(self.team.id, driver, stage="summarization"):
            record_unpriced_response(
                httpx.Response(200, request=httpx.Request("POST", "https://gateway.example.com/v1/messages"))
            )
        now = timezone.now()
        with patch(
            "products.signals.backend.temporal.signal_queries.execute_hogql_query",
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
        self._settle(task_run, "scout-1", 123_456)
        reconcile_signal_spend()
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        record_generation_request(team_id=self.team.id, run_id=task_run.id, request_id="scout-late")
        reconcile_signal_spend()
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == ["scout"]
        self._settle(task_run, "scout-late", 1)
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
                with signal_spend_scope(self.team.id, driver, stage="actionability"):
                    record_gateway_response(
                        httpx.Response(
                            200,
                            headers={"x-request-id": "example-request"},
                            request=httpx.Request("POST", "https://gateway.example.com/v1/messages"),
                        )
                    )
        assert SignalReport.objects.filter(id=report.id).exists()
        assert any(
            log["event"] == "signals.spend.accounting_failed"
            and log["stage"] == ("research" if source == "task" else "actionability")
            for log in logs
        )
