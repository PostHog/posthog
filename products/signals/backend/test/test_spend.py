import json
import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import httpx
from anthropic import APIResponseValidationError, AsyncAnthropic
from asgiref.sync import async_to_sync
from fakeredis import FakeRedis
from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError

from posthog.schema import EmbeddingModelName

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async
from posthog.token_bucket import TEST_reset_scripts

from products.ml_inference.backend.facade.contracts import DecisionResult, NoulAnswer
from products.signals.backend.emission.pipeline import check_actionability
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.backend.facade.api import emit_signal
from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import SignalReport, SignalReportTask, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.runner import _self_heal_stale_runs
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync
from products.signals.backend.spend import (
    SignalSpendSummary,
    SignalSpendUpdate,
    begin_report_spend,
    complete_signal_pipeline,
    complete_task_spend,
    finish_report_spend,
    record_llm_spend,
    record_task_spend,
    register_report_task_spend,
    report_triggering_signal,
    signal_spend_summaries,
    signal_spend_totals,
)
from products.signals.backend.spend_metadata import confirm_signal_spend_metadata, publish_signal_spend_metadata
from products.signals.backend.system_one_prompts import bundled_prompt
from products.signals.backend.tasks import settle_scout_spend
from products.signals.backend.temporal.llm import call_llm
from products.signals.backend.temporal.summary import check_report_task_settlement_activity
from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs
from products.tasks.backend.facade.billing import TaskTokenUsageUnavailable, process_pending_gateway_usage
from products.tasks.backend.models import Task, TaskRun


class TestSpendPricing(SimpleTestCase):
    @parameterized.expand([(1, 0, "0.0001"), (10_001, 1, "5.0001"), (0, 1, "4"), (123_456, 2, "20.3456")])
    def test_price_in_cents(self, cost: int, tasks: int, expected: str) -> None:
        assert cost_to_spend(cost, task_count=tasks) == Decimal(expected)


@pytest.mark.django_db(transaction=True)
def test_concurrent_generation_costs_preserve_both_writers() -> None:
    team = Team.objects.create(organization=Organization.objects.create(name="Spend test"))
    signal_id = str(uuid4())
    barrier = Barrier(2)

    def record(worker: int) -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(5):
                record_llm_spend(
                    token_cost_microusd=worker,
                    team_id=team.id,
                    signal_id=signal_id,
                    stage="grouping",
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(record, worker) for worker in (1, 2)]
        for future in futures:
            future.result(timeout=30)
    spend = SignalSpend.objects.for_team(team.id).get(signal_id=signal_id)
    assert spend.spend == Decimal("0.0015")
    assert spend.finalized_at is None


@pytest.mark.django_db(transaction=True)
def test_direct_steering_drop_finalizes_its_known_cost() -> None:
    team = Team.objects.create(
        organization=Organization.objects.create(name="Steering spend test", is_ai_data_processing_approved=True)
    )
    driver = str(uuid4())
    with (
        patch("products.signals.backend.facade.api.SignalSourceConfig.is_source_enabled", return_value=True),
        patch(
            "products.signals.backend.emission.direct_gate.steering_filters_signal", new=AsyncMock(return_value=True)
        ),
        patch("products.signals.backend.facade.api.async_connect", new=AsyncMock()) as connect,
    ):
        record_llm_spend(team_id=team.id, signal_id=driver, stage="actionability", token_cost_microusd=100)
        async_to_sync(emit_signal)(
            team=team,
            source_product="error_tracking",
            source_type="issue_created",
            source_id="synthetic-issue",
            description="Synthetic error excluded by source steering",
            extra={"fingerprint": "synthetic-fingerprint"},
            signal_id=driver,
        )
    spend = SignalSpend.objects.for_team(team.id).get(signal_id=driver)
    assert spend.finalized_at is not None
    assert spend.spend == Decimal("0.01")
    connect.assert_not_called()


class TestSignalSpend(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.temporal = AsyncMock()
        self.connect = patch("posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=self.temporal))
        self.connect.start()
        self.addCleanup(self.connect.stop)

    @parameterized.expand([("generation",), ("task",)])
    def test_clickhouse_spend_retries_until_visible_and_tracks_later_costs(self, source: str) -> None:
        driver = str(uuid4())
        signal = SignalSpendUpdate(team_id=self.team.id, signal_id=driver)
        record_llm_spend(token_cost_microusd=123, team_id=self.team.id, signal_id=driver, stage="actionability")
        now = timezone.now()
        metadata = {"report_id": "moved-report", "deleted": True, "extra": {"example": 1}, "total_spend": 0}
        rows: dict[str, list] = {}
        producer = Mock()
        scope = MagicMock()
        scope.__enter__.return_value = producer
        with (
            time_machine.travel(now + timedelta(seconds=2), tick=False) as clock,
            patch("products.signals.backend.spend_metadata.producer_scope", return_value=scope) as produce_scope,
            patch(
                "products.signals.backend.spend_metadata.execute_hogql_query",
                side_effect=lambda **kwargs: Mock(results=rows.get(kwargs["placeholders"]["model_name"].value, [])),
            ) as query,
        ):
            with self.assertRaisesRegex(RuntimeError, "not yet visible"):
                publish_signal_spend_metadata(signal)
            for model in EmbeddingModelName:
                rows[model.value] = [(driver, ("Example finding", json.dumps(metadata), now, [0.5], now))]
            produce_scope.side_effect = RuntimeError("Kafka unavailable")
            with self.assertRaises(RuntimeError):
                publish_signal_spend_metadata(signal)
            produce_scope.side_effect = None
            producer.produce.return_value.get.side_effect = RuntimeError("Kafka delivery failed")
            with self.assertRaisesRegex(RuntimeError, "Kafka delivery failed"):
                publish_signal_spend_metadata(signal)
            producer.produce.return_value.get.side_effect = None
            producer.reset_mock()
            publication = publish_signal_spend_metadata(signal)
            assert producer.produce.call_count == len(EmbeddingModelName)
            for _ in range(5):
                assert not confirm_signal_spend_metadata(publication)
            assert producer.produce.call_count == len(EmbeddingModelName)
            for call in producer.produce.call_args_list:
                payload = call.kwargs["data"]
                assert call.kwargs["key"] == f"signals:{self.team.id}:{driver}:{payload['model_name']}"
                assert json.loads(payload["metadata"]) == {
                    **metadata,
                    "total_spend": 0.0123,
                    "spend_accounting_failed_stages": [],
                }
                assert payload["content"] == "Example finding"
                assert payload["embedding"] == [0.5]
                assert payload["timestamp"] == now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                rows[payload["model_name"]] = [
                    (driver, (payload["content"], payload["metadata"], now, [0.5], timezone.now()))
                ]
            producer.reset_mock()
            assert confirm_signal_spend_metadata(publication)
            assert publish_signal_spend_metadata(signal) == publication
            producer.produce.assert_not_called()
            if source == "generation":
                record_llm_spend(
                    token_cost_microusd=123,
                    team_id=self.team.id,
                    signal_id=driver,
                    stage="report_safety_judge",
                )
                expected = 0.0246
            else:
                report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
                run = self._run(report=report)
                self._set_task_cost(run, 123)
                expected = 4.0246
            with self.assertRaisesRegex(RuntimeError, "strictly newer"):
                publish_signal_spend_metadata(signal)
            producer.produce.assert_not_called()
            clock.shift(2)
            newer = publish_signal_spend_metadata(signal)
            assert all(newer.versions[model] > version for model, version in publication.versions.items())
            assert producer.produce.call_count == len(EmbeddingModelName)
            for call in producer.produce.call_args_list:
                payload = call.kwargs["data"]
                assert json.loads(payload["metadata"])["total_spend"] == expected
                rows[payload["model_name"]] = [
                    (driver, (payload["content"], payload["metadata"], now, [0.5], timezone.now()))
                ]
            assert confirm_signal_spend_metadata(newer)
            record_llm_spend(token_cost_microusd=None, team_id=self.team.id, signal_id=driver, stage="summarization")
            producer.reset_mock()
            clock.shift(2)
            publish_signal_spend_metadata(signal)
            assert producer.produce.call_count == len(EmbeddingModelName)
            assert all(
                json.loads(call.kwargs["data"]["metadata"])["spend_accounting_failed_stages"] == ["summarization"]
                for call in producer.produce.call_args_list
            )
            assert query.call_args_list
            assert all(call.kwargs["ch_user"] == ClickHouseUser.SIGNALS for call in query.call_args_list)
        with patch(
            "products.signals.backend.signal_metadata.execute_hogql_query",
            return_value=Mock(results=[(driver, "Example finding", json.dumps(metadata), now, now)]),
        ):
            signal_row = fetch_signals_for_report_sync(self.team, str(uuid4()))[0]
            assert signal_row["total_spend"] == metadata["total_spend"]

    @parameterized.expand([("web", None, False), ("pipeline", ClickHouseUser.SIGNALS, False), ("settled", None, True)])
    def test_triggering_signal_lookup_preserves_query_identity(
        self, _name: str, ch_user: ClickHouseUser | None, finalized: bool
    ) -> None:
        report = SignalReport.objects.create(team=self.team)
        driver = str(uuid4())
        now = timezone.now()
        if finalized:
            record_llm_spend(team_id=self.team.id, signal_id=driver, stage="grouping", token_cost_microusd=100)
            complete_signal_pipeline(team_id=self.team.id, signal_id=driver)
        with patch(
            "products.signals.backend.signal_metadata.execute_hogql_query",
            return_value=Mock(results=[(driver, "Example finding", "{}", now, now)]),
        ) as query:
            assert report_triggering_signal(
                team_id=self.team.id, report_id=str(report.id), **({"ch_user": ch_user} if ch_user else {})
            ) == (None if finalized else driver)
        assert query.call_args.kwargs["ch_user"] == (ch_user or ClickHouseUser.DEFAULT)
        report.refresh_from_db()
        assert (str(report.triggering_signal_id) if report.triggering_signal_id else None) == (
            None if finalized else driver
        )

    @parameterized.expand([("priced", 12_345), ("free", 0), ("cancelled", None), ("missing_id", None)])
    async def test_generation_waits_for_spend_without_regenerating(self, outcome: str, cost: int | None) -> None:
        driver = str(uuid4())
        response = Mock(_request_id=None if outcome == "missing_id" else "generation-1")
        generate = AsyncMock(return_value=response)
        with (
            patch(
                "products.signals.backend.llm_spend.fetch_gateway_cost",
                new=AsyncMock(
                    side_effect=[None, None, GatewayRequestCost(model="model", provider="provider", cost_microusd=cost)]
                    if cost is not None
                    else [None]
                ),
            ) as lookup,
            patch(
                "products.signals.backend.llm_spend.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError if outcome == "cancelled" else None),
            ),
        ):
            generation = generate_with_spend(
                generate(),
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                team_id=self.team.id,
                signal_id=driver,
                stage="summarization",
            )
            if outcome == "cancelled":
                with self.assertRaises(asyncio.CancelledError):
                    await generation
            elif outcome == "missing_id":
                priced = await generation
                assert priced.response is response
                assert priced.spend is None
                lookup.assert_not_awaited()
            else:
                priced = await generation
                assert priced.response is response
                assert cost is not None
                assert priced.spend == Decimal(cost) / 10_000
                assert lookup.await_count == 3
            generate.assert_awaited_once()
        spend = await database_sync_to_async(lambda: SignalSpend.objects.for_team(self.team.id).get(signal_id=driver))()
        assert spend.spend == cost_to_spend(cost or 0)
        assert spend.accounting_failed is (cost is None)
        assert spend.llm_failed_stages == (["summarization"] if cost is None else [])

    @parameterized.expand([("unavailable",), ("hung",), ("activity_deadline",)])
    async def test_usage_timeout_preserves_completed_generation(self, outcome: str) -> None:
        driver = str(uuid4())
        response = Mock(_request_id="generation-1")
        generate = AsyncMock(return_value=response)

        async def lookup(*args: object, **kwargs: object) -> None:
            if outcome == "hung":
                await asyncio.Event().wait()
            return None

        now = timezone.now()
        info = SimpleNamespace(
            started_time=now - timedelta(seconds=5),
            scheduled_time=now - timedelta(seconds=5),
            start_to_close_timeout=timedelta(seconds=5),
            schedule_to_close_timeout=timedelta(seconds=60),
        )
        with (
            patch("products.signals.backend.llm_spend.USAGE_WAIT_SECONDS", 0.01),
            patch(
                "products.signals.backend.llm_spend.activity.in_activity", return_value=outcome == "activity_deadline"
            ),
            patch("products.signals.backend.llm_spend.activity.info", return_value=info),
            patch("products.signals.backend.llm_spend.fetch_gateway_cost", new=AsyncMock(side_effect=lookup)),
        ):
            priced = await generate_with_spend(
                generate(),
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                team_id=self.team.id,
                signal_id=driver,
                stage="actionability",
            )
        assert priced.response is response
        assert priced.spend is None
        generate.assert_awaited_once()
        receipt = await database_sync_to_async(
            lambda: SignalSpend.objects.for_team(self.team.id).get(signal_id=driver)
        )()
        assert receipt.accounting_failed is True
        assert receipt.llm_failed_stages == ["actionability"]

    @parameterized.expand(
        [(gateway, failure) for gateway in (True, False) for failure in ("timeout", "transport", "cancelled")]
    )
    async def test_failed_generation_records_stage_before_propagating(self, use_gateway: bool, failure: str) -> None:
        driver = str(uuid4())
        error = {
            "timeout": TimeoutError(),
            "transport": httpx.ReadError("connection lost"),
            "cancelled": asyncio.CancelledError(),
        }[failure]
        generate = AsyncMock(side_effect=error)
        with self.assertRaises(type(error)):
            await generate_with_spend(
                generate(),
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key")
                if use_gateway
                else None,
                team_id=self.team.id,
                signal_id=driver,
                stage="actionability",
            )
        spend = await database_sync_to_async(lambda: SignalSpend.objects.for_team(self.team.id).get(signal_id=driver))()
        assert spend.accounting_failed is True
        assert spend.llm_failed_stages == ["actionability"]
        generate.assert_awaited_once()

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
                patch(
                    "products.signals.backend.llm_spend.fetch_gateway_cost",
                    new=AsyncMock(
                        return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)
                    ),
                ),
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
        assert spend.llm_failed_stages == (["safety"] if failure == "invalid_json" else [])
        assert spend.accounting_failed is (failure == "invalid_json")

    @parameterized.expand([("gateway",), ("legacy",)])
    async def test_parallel_generations_record_every_attempt_for_the_explicit_owner(self, mode: str) -> None:
        drivers = [str(uuid4()), str(uuid4())]
        attempts: dict[str, int] = {}

        async def respond(request: httpx.Request) -> httpx.Response:
            key = json.loads(request.content)["messages"][0]["content"]
            attempts[key] = attempts.get(key, 0) + 1
            return httpx.Response(
                200,
                headers={"x-request-id": f"{key}-{attempts[key]}", "request-id": f"{key}-{attempts[key]}"},
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
            patch(
                "products.signals.backend.llm_spend.fetch_gateway_cost",
                new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
            ),
        ):
            results = await asyncio.gather(call(drivers[0], "request-a"), call(drivers[1], "request-b"))
            assert list(results) == ["ok", "ok"]
            assert await call(None, "unattributed") == "ok"
        rows = await database_sync_to_async(lambda: list(SignalSpend.objects.for_team(self.team.id).values()))()
        assert await database_sync_to_async(
            lambda: signal_spend_totals(team_id=self.team.id, signal_ids=drivers)
        )() == {drivers[0]: 0.0246 if mode == "gateway" else 0, drivers[1]: 0.0123 if mode == "gateway" else 0}
        assert len(rows) == 2
        assert {str(row["signal_id"]) for row in rows} == set(drivers)
        assert all(row["accounting_failed"] is (mode != "gateway") for row in rows)

    @parameterized.expand(
        [
            ("system-one-only", True),
            ("system-one-shadow", True),
            ("traditional-shadow", True),
            ("traditional-only", False),
        ]
    )
    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="phs_test")
    async def test_system_one_is_excluded_from_spend_while_traditional_calls_are_accounted(
        self, mode: str, request_id_available: bool
    ) -> None:
        driver = str(uuid4())
        output = SignalEmitterOutput(
            signal_id=driver,
            source_id="issue-1",
            source_product="linear",
            source_type="issue",
            description="An example finding",
            weight=1.0,
            extra={},
        )
        result = DecisionResult(
            model="jevk5-fp8-0.2",
            answers={"actionable": NoulAnswer(probability=0.98)},
            input_tokens=10,
        )
        client = Mock()
        client.messages.create = AsyncMock(
            return_value=Mock(
                content=[Mock(type="text", text="ACTIONABLE" if request_id_available else "NOT_ACTIONABLE")],
                _request_id="traditional-request" if request_id_available else None,
            )
        )
        TEST_reset_scripts()
        try:
            with (
                patch(
                    "products.signals.backend.llm_spend.fetch_gateway_cost",
                    new=AsyncMock(
                        return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)
                    ),
                ),
                patch("products.signals.backend.system_one_decision.get_client", return_value=FakeRedis()),
                patch("products.signals.backend.system_one_decision.model_mode", new=AsyncMock(return_value=mode)),
                patch("products.signals.backend.system_one_decision.posthoganalytics.capture"),
                patch(
                    "products.signals.backend.system_one_decision.decision_api.decide_when_available",
                    return_value=result,
                ),
            ):
                assert (
                    await check_actionability(
                        client,
                        self.team.id,
                        output,
                        "Is this actionable? {description}",
                        gateway_mode=True,
                        system_one_prompt=bundled_prompt("example-prompt", "policy", "Actionable?", 0.9),
                    )
                    is request_id_available
                )
        finally:
            TEST_reset_scripts()
        rows = await database_sync_to_async(lambda: list(SignalSpend.objects.for_team(self.team.id).values()))()
        if mode == "system-one-only":
            assert rows == []
        else:
            assert len(rows) == 1
            assert str(rows[0]["signal_id"]) == driver
            assert rows[0]["spend"] == (Decimal("0.0123") if request_id_available else 0)
            assert rows[0]["accounting_failed"] is (not request_id_available)
            client.messages.create.assert_awaited_once()

    def _run(
        self,
        *,
        report: SignalReport | None = None,
        task: Task | None = None,
        stage: str = "research",
        signal_id: str | None = None,
        implementation_kind: str | None = None,
    ) -> TaskRun:
        task = task or Task.objects.create(
            team=self.team,
            title="Example research",
            description="",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report=report,
        )
        run = task.create_run(
            environment=TaskRun.Environment.CLOUD,
            spend_signal_id=signal_id,
            implementation_spend_kind=implementation_kind,
            extra_state={"ai_stage": stage, "unprocessed_request_ids": [], "token_cost": {}},
        )
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        return run

    def _complete_task_spend(self, *, team_id: int, run_id: str) -> None:
        run = TaskRun.objects.select_related("task").get(team_id=team_id, id=run_id)
        complete_task_spend(
            team_id=team_id,
            run_id=run_id,
            report_id=str(run.task.signal_report_id) if run.task.signal_report_id else None,
        )

    def test_settlement_waits_for_only_the_triggering_signals_task_workflows(self) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        self._run(report=report, signal_id=str(uuid4()))
        run = self._run(report=report, signal_id=driver)
        handle = AsyncMock()
        self.temporal.get_workflow_handle = Mock(return_value=handle)
        inputs = SignalReportSummaryWorkflowInputs(team_id=self.team.id, report_id=str(report.id), signal_id=driver)
        with patch(
            "products.signals.backend.temporal.summary.async_connect", new=AsyncMock(return_value=self.temporal)
        ):
            handle.describe.return_value.status = WorkflowExecutionStatus.RUNNING
            with self.assertRaisesRegex(ApplicationError, "still settling"):
                async_to_sync(check_report_task_settlement_activity)(inputs)
            self.temporal.get_workflow_handle.assert_called_once_with(run.workflow_id)
            handle.describe.return_value.status = WorkflowExecutionStatus.COMPLETED
            async_to_sync(check_report_task_settlement_activity)(inputs)

    def _refresh_task_spend(self, *, run_id: str, team_id: int) -> None:
        run = TaskRun.objects.get(id=run_id, team_id=team_id)
        spend = SignalSpend.objects.for_team(team_id).filter(task_run_id=run.id).first()
        if spend:
            assert spend.kind is not None
            record_task_spend(
                team_id=team_id,
                run_id=run_id,
                signal_id=str(spend.signal_id) if spend.signal_id else None,
                scout_run_id=str(spend.scout_run_id) if spend.scout_run_id else None,
                report_id=str(spend.report_id) if spend.report_id else None,
                stage="scout" if spend.scout_run_id else "implementation" if spend.report_id else spend.kind,
                implementation_kind=spend.kind if spend.report_id else None,
            )

    def _set_task_cost(self, run: TaskRun, cost: int | None, *, pending: bool = False) -> None:
        run.refresh_from_db()
        previous = sum(
            bucket.get("cost_microusd", 0)
            for providers in run.state.get("token_cost", {}).values()
            for bucket in providers.values()
        )
        request_id = str(uuid4())
        run.state["unprocessed_request_ids"] = [request_id]
        run.state.setdefault("token_cost", {})
        run.save(update_fields=["state"])
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new=AsyncMock(
                return_value=GatewayRequestCost(model="model-a", provider="provider-a", cost_microusd=cost - previous)
                if cost is not None
                else None
            ),
        ):
            process_pending_gateway_usage(run_id=run.id, team_id=run.team_id)
        if pending:
            run.refresh_from_db()
            run.state["unprocessed_request_ids"] = ["pending-request"]
            run.save(update_fields=["state"])
        self._refresh_task_spend(run_id=str(run.id), team_id=self.team.id)

    @parameterized.expand([("research",), ("repo_selection",)])
    def test_task_cost_updates_charge_exact_run_once(self, stage: str) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report, stage=stage)
        self._set_task_cost(run, 10_001)
        report.triggering_signal_id = other
        report.save(update_fields=["triggering_signal_id"])
        self._set_task_cost(run, 10_004)
        register_report_task_spend(
            team_id=self.team.id, run_id=str(run.id), report_id=str(report.id), stage=stage, signal_id=other
        )
        rerun = self._run(task=run.task, stage=stage, signal_id=other)
        self._set_task_cost(rerun, 1)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 5.0004, other: 4.0001}
        rows = SignalSpend.objects.for_team(self.team.id)
        assert rows.get(task_run_id=run.id).signal_id == UUID(driver)
        assert rows.get(task_run_id=rerun.id).signal_id == UUID(other)
        assert set(rows.values_list("kind", flat=True)) == {stage}

    @parameterized.expand([("reviewer_triggered_implementation",), ("scout_triggered_implementation",)])
    def test_each_kind_finalizes_independently_and_new_implementation_keeps_settled_rows(
        self, implementation_kind: str
    ) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(
            team=self.team, triggering_signal_id=driver, status=SignalReport.Status.CANDIDATE
        )
        record_llm_spend(token_cost_microusd=100, team_id=self.team.id, signal_id=driver, stage="grouping")
        complete_signal_pipeline(team_id=self.team.id, signal_id=driver, report_id=str(report.id))
        research = self._run(report=report)
        repo = self._run(report=report, stage="repo_selection")
        for run in (research, repo):
            self._set_task_cost(run, 10_000)
            run.status = TaskRun.Status.COMPLETED
            run.save(update_fields=["status"])
            self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        rows = SignalSpend.objects.for_team(self.team.id)
        assert rows.filter(signal_id=driver, finalized_at__isnull=False).count() == 2
        implementation = self._run(report=report, stage="implementation", implementation_kind=implementation_kind)
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=driver)
        assert rows.filter(signal_id=driver, finalized_at__isnull=False).count() == 3
        before = list(rows.filter(signal_id=driver).order_by("id").values())
        for run in (
            implementation,
            self._run(task=implementation.task, stage="implementation", implementation_kind=implementation_kind),
        ):
            self._set_task_cost(run, 20_000)
            run.status = TaskRun.Status.COMPLETED
            run.save(update_fields=["status"])
            self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            row = rows.get(task_run_id=run.id)
            assert row.report_id == report.id
            assert row.signal_id is None
            assert row.kind == implementation_kind
            assert row.spend == Decimal(6)
            assert row.finalized_at is not None
        assert list(rows.filter(signal_id=driver).order_by("id").values()) == before
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 10.01}
        assert rows.filter(report=report).count() == 2

    @parameterized.expand(
        [
            (Task.OriginProduct.SIGNAL_REPORT, "inbox"),
            (Task.OriginProduct.SIGNAL_REPORT, ""),
            (Task.OriginProduct.SIGNALS_SCOUT, ""),
        ]
    )
    def test_manual_report_run_leaves_finalized_signal_spend_unchanged(self, origin: str, stage: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(
            team=self.team, triggering_signal_id=driver, status=SignalReport.Status.READY
        )
        if origin == Task.OriginProduct.SIGNALS_SCOUT:
            task = Task.objects.create(team=self.team, title="Scout", origin_product=origin)
            run = self._run(task=task, stage="scout")
            scout = SignalScoutRun.objects.for_team(self.team.id).create(
                team=self.team, task_run=run, skill_name="example-scout", skill_version=1
            )
            record_task_spend(team_id=self.team.id, run_id=str(run.id), scout_run_id=str(scout.id), stage="scout")
        else:
            run = self._run(report=report, stage="implementation")
            SignalReportTask.objects.create(team=self.team, report=report, task=run.task, relationship="implementation")
        self._set_task_cost(run, 100)
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        before = SignalSpend.objects.for_team(self.team.id).values().get()
        assert before["finalized_at"] is not None
        resumed = self._run(task=run.task, stage=stage)
        assert resumed.state["billing_product"] == "posthog_ai"
        self._set_task_cost(resumed, 200)
        resumed.status = TaskRun.Status.COMPLETED
        resumed.save(update_fields=["status"])
        self._complete_task_spend(team_id=self.team.id, run_id=str(resumed.id))
        assert SignalSpend.objects.for_team(self.team.id).values().get() == before

    @parameterized.expand([(Task.OriginProduct.SIGNAL_REPORT, "research"), (Task.OriginProduct.SIGNALS_SCOUT, "scout")])
    def test_prelaunch_failure_settles_with_zero_tokens(self, origin: str, stage: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        task = Task.objects.create(
            team=self.team, title="Fails before launch", origin_product=origin, signal_report=report
        )
        run = task.create_run(
            environment=TaskRun.Environment.CLOUD, extra_state={"ai_stage": stage}, spend_signal_id=driver
        )
        if origin == Task.OriginProduct.SIGNALS_SCOUT:
            scout = SignalScoutRun.objects.for_team(self.team.id).create(
                team=self.team, task_run=run, skill_name="example-scout", skill_version=1
            )
            record_task_spend(team_id=self.team.id, run_id=str(run.id), scout_run_id=str(scout.id), stage="scout")
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["status"])
        self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert spend.finalized_at is not None
        assert not spend.accounting_failed
        assert spend.spend == cost_to_spend(0, task_count=1)

    @parameterized.expand([("research",), ("repo_selection",)])
    def test_resumed_task_belongs_to_new_signal_and_preserves_finalized_owner(self, stage: str) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report, stage=stage)
        self._set_task_cost(run, 100)
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        before = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        resumed = self._run(task=run.task, stage=stage, signal_id=other)
        self._set_task_cost(resumed, 200)
        resumed.status = TaskRun.Status.FAILED
        resumed.save(update_fields=["status"])
        self.temporal.start_workflow.side_effect = RuntimeError("Temporal unavailable")
        with self.assertRaisesRegex(RuntimeError, "Temporal unavailable"):
            self._complete_task_spend(team_id=self.team.id, run_id=str(resumed.id))
        settled = SignalSpend.objects.for_team(self.team.id).get(task_run_id=resumed.id)
        assert settled.finalized_at is not None
        assert settled.spend == Decimal("4.02")
        self.temporal.start_workflow.side_effect = None
        self._complete_task_spend(team_id=self.team.id, run_id=str(resumed.id))
        register_report_task_spend(
            team_id=self.team.id, run_id=str(run.id), report_id=str(report.id), stage=stage, signal_id=other
        )
        after = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert (after.signal_id, after.spend, after.finalized_at) == (
            before.signal_id,
            before.spend,
            before.finalized_at,
        )
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 4.01, other: 4.02}
        assert SignalSpend.objects.for_team(self.team.id).get(task_run_id=resumed.id).finalized_at is not None

    @parameterized.expand([(SignalReport.Status.READY,), (SignalReport.Status.CANDIDATE,)])
    def test_pipeline_handoff_stays_open_until_summary_completion(self, status: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver, status=status)
        record_llm_spend(token_cost_microusd=100, team_id=self.team.id, signal_id=driver, stage="grouping")
        complete_signal_pipeline(team_id=self.team.id, signal_id=driver, report_id=str(report.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=driver)
        self.assertIsNone(spend.finalized_at)
        finish_report_spend(team_id=self.team.id, signal_id=driver, report_id=str(report.id))
        spend.refresh_from_db()
        self.assertIsNotNone(spend.finalized_at)

    @parameterized.expand([("terminal", False, False), ("next_pass", True, False), ("newer_pass", True, True)])
    def test_summary_completion_settles_only_abandoned_pending_trigger(
        self, _name: str, next_pass: bool, newer_pass: bool
    ) -> None:
        driver, pending = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE if next_pass else SignalReport.Status.POTENTIAL,
            triggering_signal_id=str(uuid4()) if newer_pass else pending if next_pass else driver,
            pending_triggering_signal_id=pending,
        )
        for signal_id in (driver, pending):
            record_llm_spend(token_cost_microusd=100, team_id=self.team.id, signal_id=signal_id, stage="grouping")
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=driver)
        rows = SignalSpend.objects.for_team(self.team.id)
        assert rows.get(signal_id=driver).finalized_at is not None
        assert (rows.get(signal_id=pending).finalized_at is None) == next_pass
        report.refresh_from_db()
        assert (report.pending_triggering_signal_id is not None) == next_pass

    def test_filtered_signal_finalizes_only_when_every_source_is_priced(self) -> None:
        driver = str(uuid4())
        record_llm_spend(token_cost_microusd=100, team_id=self.team.id, signal_id=driver, stage="summarization")
        record_llm_spend(token_cost_microusd=None, team_id=self.team.id, signal_id=driver, stage="actionability")
        complete_signal_pipeline(team_id=self.team.id, signal_id=driver)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=driver)
        self.assertIsNone(spend.finalized_at)
        assert spend.accounting_failed
        assert spend.spend == Decimal("0.01")
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, str(uuid4())]) == {driver: 0.01}
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignalSpend.objects.for_team(self.team.id).create(
                team_id=self.team.id, signal_id=driver, kind=SignalSpend.Kind.AD_HOC
            )

    def test_reset_discards_receipts_and_keeps_the_existing_table(self) -> None:
        migration = import_module("products.signals.backend.migrations.0208_reset_signal_spend")
        with override_settings(MIGRATION_MODULES={}):
            state = MigrationLoader(connection).project_state([("signals", "0207_backfill_report_link_targets")])
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA test_signal_spend_reset")
            cursor.execute("SET LOCAL search_path TO test_signal_spend_reset, public")
        try:
            old_spend = state.apps.get_model("signals", "SignalSpend")
            with connection.schema_editor() as editor:
                editor.create_model(old_spend)
            old_spend.objects.create(
                team_id=self.team.id,
                signal_id=uuid4(),
                source_id="discarded-call",
                token_cost_microusd=10_000,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute("SELECT 'signals_signalspend'::regclass::oid")
                original_table = cursor.fetchone()[0]
            with connection.schema_editor() as editor:
                state = migration.Migration("0208_reset_signal_spend", "signals").apply(state, editor)
            spend = state.apps.get_model("signals", "SignalSpend")
            assert not spend.objects.exists()
            row = spend.objects.create(
                team_id=self.team.id,
                signal_id=uuid4(),
                kind="research",
                task_run_id=uuid4(),
                spend=Decimal("4.0123"),
                finalized_at=timezone.now(),
            )
            assert spend.objects.get(id=row.id).spend == Decimal("4.0123")
            legacy_signal = old_spend.objects.create(
                team_id=self.team.id,
                signal_id=row.signal_id,
                source_id="overlapping-call",
                token_cost_microusd=20_000,
                accounting_failed=True,
            )
            legacy_scout = old_spend.objects.create(
                team_id=self.team.id,
                scout_run_id=uuid4(),
                source_id=str(uuid4()),
                is_task=True,
            )
            legacy_scout.token_cost_microusd = 30_000
            legacy_scout.save(update_fields=["token_cost_microusd"])
            assert old_spend.objects.get(id=legacy_scout.id).token_cost_microusd == 30_000
            assert list(
                spend.objects.filter(id__in=[legacy_signal.id, legacy_scout.id]).values_list(
                    "kind", "spend", "finalized_at"
                )
            ) == [(None, Decimal(0), None), (None, Decimal(0), None)]
            assert signal_spend_summaries(team_id=self.team.id, signal_ids=[str(row.signal_id)]) == {
                str(row.signal_id): SignalSpendSummary(total_spend=4.0123, failed_stages=[])
            }
            with self.assertRaises(IntegrityError), transaction.atomic():
                spend.objects.filter(id=legacy_signal.id).update(finalized_at=timezone.now())
            with connection.cursor() as cursor:
                cursor.execute("SELECT 'signals_signalspend'::regclass::oid")
                assert cursor.fetchone()[0] == original_table
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL search_path TO public")
                cursor.execute("DROP SCHEMA test_signal_spend_reset CASCADE")

    @parameterized.expand([("research",), ("repo_selection",), ("implementation",), ("scout",)])
    def test_completion_does_not_recreate_discarded_spend(self, stage: str) -> None:
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        run = self._run(report=report, stage=stage)
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        if stage == "scout":
            scout = SignalScoutRun.objects.for_team(self.team.id).create(
                team=self.team, task_run=run, skill_name="example-scout", skill_version=1
            )
            record_task_spend(team_id=self.team.id, run_id=str(run.id), scout_run_id=str(scout.id), stage="scout")
        SignalSpend.objects.for_team(self.team.id).filter(task_run_id=run.id).delete()
        self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        assert not SignalSpend.objects.for_team(self.team.id).exists()

    def test_task_binding_cannot_charge_a_second_owner(self) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report)
        self._set_task_cost(run, 1)
        with self.assertRaisesRegex(ValueError, "already owned"):
            record_task_spend(team_id=self.team.id, run_id=str(run.id), signal_id=other, stage="research")
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 4.0001}

    def test_gateway_request_and_owner_delta_roll_back_together(self) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report)
        run.state["unprocessed_request_ids"] = ["example-request"]
        run.save(update_fields=["state"])

        def refuse_owner_write(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith('UPDATE "signals_signalspend"'):
                raise RuntimeError("Owner write failed")
            return execute(sql, params, many, context)

        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
        ):
            with (
                connection.execute_wrapper(refuse_owner_write),
                self.assertRaisesRegex(RuntimeError, "Owner write failed"),
            ):
                process_pending_gateway_usage(run_id=run.id, team_id=self.team.id)
            run.refresh_from_db()
            assert run.state["unprocessed_request_ids"] == ["example-request"]
            assert run.state["token_cost"] == {}
            for _ in range(2):
                process_pending_gateway_usage(run_id=run.id, team_id=self.team.id)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 4.0123}

    def test_spend_reads_do_not_reopen_or_bill_a_completed_owner(self) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        record_llm_spend(token_cost_microusd=0, team_id=self.team.id, signal_id=driver, stage="grouping")
        run = self._run(report=report)
        self._set_task_cost(run, 10_000)
        SignalSpend.objects.for_team(self.team.id).filter(signal_id=driver).update(finalized_at=timezone.now())
        before = list(SignalSpend.objects.for_team(self.team.id).filter(signal_id=driver).order_by("id").values())
        run.state = {"ai_stage": "research", "token_cost": {"model": {"provider": {"cost_microusd": 20_000}}}}
        run.save(update_fields=["state"])
        with CaptureQueriesContext(connection) as queries:
            assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 5}
        assert all(query["sql"].startswith("SELECT") and "FOR UPDATE" not in query["sql"] for query in queries)
        self._refresh_task_spend(team_id=self.team.id, run_id=str(run.id))
        begin_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=driver)
        with self.assertRaises(ValueError):
            record_llm_spend(token_cost_microusd=100, team_id=self.team.id, signal_id=driver, stage="grouping")
        complete_signal_pipeline(team_id=self.team.id, signal_id=driver)
        assert (
            list(SignalSpend.objects.for_team(self.team.id).filter(signal_id=driver).order_by("id").values()) == before
        )

    def test_report_reassignment_and_deletion_do_not_leave_spend_open(self) -> None:
        driver = str(uuid4())
        first, second = [
            SignalReport.objects.create(team=self.team, triggering_signal_id=driver, status=SignalReport.Status.READY)
            for _ in range(2)
        ]
        for report in [first, second]:
            begin_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=driver)
        report_id = str(second.id)
        second.delete()
        finish_report_spend(team_id=self.team.id, signal_id=driver, report_id=report_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=driver)
        self.assertIsNotNone(spend.finalized_at)

    def test_task_cost_updates_spend_synchronously_without_publishing(self) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report)
        with transaction.atomic():
            self._set_task_cost(run, 10_001)
            assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 5.0001}
            self.temporal.start_workflow.assert_not_called()
        try:
            with transaction.atomic():
                self._set_task_cost(run, 20_002)
                assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 6.0002}
                raise RuntimeError("roll back task cost")
        except RuntimeError:
            pass
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 5.0001}
        self.temporal.start_workflow.assert_not_called()

    @parameterized.expand([("research", True), ("repo_selection", True), ("implementation", False)])
    def test_only_signal_owned_tasks_publish_signal_metadata(self, stage: str, publishes: bool) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=report, stage=stage)
        self._set_task_cost(run, 10_001)
        report.billing_exempt_reason = SignalReport.BillingExemptReason.POSTHOG_SYSTEM
        report.save(update_fields=["billing_exempt_reason"])
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
        assert self.temporal.start_workflow.await_count == int(publishes)
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert spend.spend == Decimal("5.0001")
        assert spend.finalized_at is not None
        assert spend.billing_exempt

    @parameterized.expand([(False,), (True,)])
    @override_settings(SANDBOX_AI_GATEWAY_URL="https://gateway.example", SANDBOX_AI_GATEWAY_MINT_KEY="test-key")
    def test_completion_settles_pending_task_usage_inline(self, is_scout: bool) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        run = self._run(report=None if is_scout else report)
        scout = (
            SignalScoutRun.objects.for_team(self.team.id).create(
                team=self.team, task_run=run, skill_name="example-scout", skill_version=1
            )
            if is_scout
            else None
        )
        if scout:
            record_task_spend(team_id=self.team.id, run_id=str(run.id), scout_run_id=str(scout.id), stage="scout")
        run.state = {"ai_stage": "research", "unprocessed_request_ids": ["pending-request"], "token_cost": {}}
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["state", "status"])
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new=AsyncMock(return_value=None),
        ) as fetch:
            with self.assertRaises(TaskTokenUsageUnavailable):
                self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            owner = SignalSpend.objects.for_team(self.team.id).get(
                **({"scout_run_id": scout.id} if scout else {"signal_id": driver})
            )
            assert owner.accounting_failed
            assert owner.finalized_at is None
            self.temporal.start_workflow.assert_not_called()
            fetch.reset_mock()
            fetch.return_value = GatewayRequestCost(model="example", provider="example", cost_microusd=123_456)
            self._complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            fetch.assert_awaited_once_with("pending-request")
        if scout:
            scout.refresh_from_db()
            assert scout.total_spend == Decimal("16.3456")
            assert scout.metadata is not None
            assert scout.metadata["spend_accounting_failed_stages"] == []
        else:
            summary = signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver]
            assert summary.total_spend == 16.3456
            assert summary.failed_stages == []
        assert self.temporal.start_workflow.await_count == (0 if is_scout else 1)

    def test_one_shot_calls_preserve_known_spend_and_record_failed_stage(self) -> None:
        driver = str(uuid4())
        for cost in (None, 9, None):
            record_llm_spend(token_cost_microusd=cost, team_id=self.team.id, signal_id=driver, stage="actionability")
        summary = signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver]
        assert summary.total_spend == 0.0009
        assert summary.failed_stages == ["actionability"]
        record_llm_spend(token_cost_microusd=1, team_id=self.team.id, signal_id=driver, stage="actionability")
        assert SignalSpend.objects.for_team(self.team.id).count() == 1
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 0.001}
        assert signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver].failed_stages == [
            "actionability"
        ]
        record_llm_spend(token_cost_microusd=None, team_id=self.team.id, signal_id=driver, stage="summarization")
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        assert signal_spend_totals(team_id=other_team.id, signal_ids=[driver]) == {}

    @parameterized.expand([(False,), (True,)])
    def test_scout_persists_spend_in_cents_after_failed_run_settles(self, settled_before_owner: bool) -> None:
        task_run = self._run()
        if settled_before_owner:
            self._set_task_cost(task_run, 123_456, pending=True)
        with self.captureOnCommitCallbacks(execute=True):
            scout = SignalScoutRun.objects.for_team(self.team.id).create(
                team=self.team,
                task_run=task_run,
                skill_name="example-scout",
                skill_version=1,
            )
        scout.created_at -= timedelta(days=1)
        scout.save(update_fields=["created_at"])
        record_task_spend(team_id=self.team.id, run_id=str(task_run.id), scout_run_id=str(scout.id), stage="scout")
        assert SignalSpend.objects.for_team(self.team.id).get(scout_run=scout).created_at == scout.created_at
        assert scout.total_spend is None
        scout.refresh_from_db()
        assert scout.total_spend == (Decimal("16.3456") if settled_before_owner else Decimal("4"))
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == (["scout"] if settled_before_owner else [])
        task_run.status = TaskRun.Status.FAILED
        task_run.save(update_fields=["status"])
        self._set_task_cost(task_run, 123_456)
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        self._set_task_cost(task_run, None)
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3456")
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == ["scout"]
        self._set_task_cost(task_run, 123_457)
        scout.refresh_from_db()
        assert scout.total_spend == Decimal("16.3457")
        assert scout.metadata is not None
        assert scout.metadata["spend_accounting_failed_stages"] == []

    @parameterized.expand([(TaskRun.Status.IN_PROGRESS,), (TaskRun.Status.COMPLETED,)])
    def test_reaped_scout_retries_accounting_until_gateway_cost_settles(self, status: str) -> None:
        run = self._run()
        if status == TaskRun.Status.COMPLETED:
            run.state["timed_out_inactivity"] = True
        run.state["unprocessed_request_ids"] = ["late-scout-request"]
        run.status = status
        run.created_at = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S + 60)
        run.save(update_fields=["state", "status", "created_at"])
        scout = SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team, task_run=run, skill_name="example-scout", skill_version=1
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), scout_run_id=str(scout.id), stage="scout")
        with (
            patch("products.signals.backend.tasks.settle_scout_spend.delay") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            _self_heal_stale_runs(self.team.id, "example-scout")
            _self_heal_stale_runs(self.team.id, "example-scout")
        enqueue.assert_called_once_with(team_id=self.team.id, run_id=str(run.id))
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost", new=AsyncMock(return_value=None)
        ):
            with self.assertRaises(TaskTokenUsageUnavailable):
                settle_scout_spend(team_id=self.team.id, run_id=str(run.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(scout_run=scout)
        assert spend.finalized_at is None
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=123_456)),
        ):
            settle_scout_spend(team_id=self.team.id, run_id=str(run.id))
        spend = SignalSpend.objects.for_team(self.team.id).get(scout_run=scout)
        assert spend.finalized_at is not None
        assert spend.spend == Decimal("16.3456")

    @parameterized.expand([("generation",), ("task",), ("pipeline",), ("report_start",)])
    def test_accounting_failure_does_not_silently_create_untracked_work(self, source: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)

        def fail_spend_query(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith('INSERT INTO "signals_signalspend"'):
                raise RuntimeError("Accounting unavailable")
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(fail_spend_query),
            self.assertRaisesRegex(RuntimeError, "Accounting unavailable"),
        ):
            if source == "task":
                self._run(report=report)
            elif source == "pipeline":
                complete_signal_pipeline(team_id=self.team.id, signal_id=driver)
            elif source == "report_start":
                begin_report_spend(team_id=self.team.id, signal_id=driver, report_id=str(report.id))
            else:
                record_llm_spend(token_cost_microusd=123, team_id=self.team.id, signal_id=driver, stage="actionability")
        assert not SignalSpend.objects.for_team(self.team.id).exists()
        assert not TaskRun.objects.filter(team_id=self.team.id).exists()
