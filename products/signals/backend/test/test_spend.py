import json
import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from django.db import connection, transaction
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import httpx
from anthropic import APIResponseValidationError, AsyncAnthropic
from asgiref.sync import async_to_sync
from fakeredis import FakeRedis
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.schema import EmbeddingModelName

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.token_bucket import TEST_reset_scripts

from products.ml_inference.backend.facade.contracts import DecisionResult, NoulAnswer
from products.signals.backend.emission.pipeline import check_actionability
from products.signals.backend.emission.registry import SignalEmitterOutput
from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import SignalReport, SignalReportTask, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync
from products.signals.backend.spend import (
    SignalSpendUpdate,
    complete_task_spend,
    publish_report_spend,
    record_llm_spend,
    report_triggering_signal,
    settle_signal_task_spend,
    signal_spend_summaries,
    signal_spend_totals,
)
from products.signals.backend.spend_metadata import confirm_signal_spend_metadata, publish_signal_spend_metadata
from products.signals.backend.system_one_prompts import bundled_prompt
from products.signals.backend.temporal.llm import call_llm
from products.tasks.backend.facade.task_run_signals import task_run_cost_updated
from products.tasks.backend.models import Task, TaskRun


class TestSpendPricing(SimpleTestCase):
    @parameterized.expand([(1, 0, "0.0001"), (10_001, 1, "5.0001"), (0, 1, "4"), (123_456, 2, "20.3456")])
    def test_price_in_cents(self, cost: int, tasks: int, expected: str) -> None:
        assert cost_to_spend(cost, task_count=tasks) == Decimal(expected)


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
        record_llm_spend(
            "first", token_cost_microusd=123, team_id=self.team.id, signal_id=driver, stage="actionability"
        )
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
                    "later",
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
            record_llm_spend(
                None, token_cost_microusd=None, team_id=self.team.id, signal_id=driver, stage="summarization"
            )
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

    @parameterized.expand([("web", None), ("pipeline", ClickHouseUser.SIGNALS)])
    def test_triggering_signal_lookup_preserves_query_identity(
        self, _name: str, ch_user: ClickHouseUser | None
    ) -> None:
        report = SignalReport.objects.create(team=self.team)
        driver = str(uuid4())
        now = timezone.now()
        with patch(
            "products.signals.backend.signal_metadata.execute_hogql_query",
            return_value=Mock(results=[(driver, "Example finding", "{}", now, now)]),
        ) as query:
            assert (
                report_triggering_signal(
                    team_id=self.team.id, report_id=str(report.id), **({"ch_user": ch_user} if ch_user else {})
                )
                == driver
            )
        assert query.call_args.kwargs["ch_user"] == (ch_user or ClickHouseUser.DEFAULT)
        report.refresh_from_db()
        assert str(report.triggering_signal_id) == driver

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
        assert spend.token_cost_microusd == cost
        assert spend.accounting_failed is (cost is None)
        assert spend.stage == "summarization"

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
        assert receipt.source_id == "generation-1"
        assert receipt.accounting_failed is True
        assert receipt.stage == "actionability"

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
        assert spend.stage == "actionability"
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
        assert spend.stage == "safety"
        assert spend.accounting_failed is (failure == "invalid_json")
        if failure == "invalid_json":
            assert spend.source_id.startswith("unknown-")
        else:
            assert spend.source_id == "generation-1"

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
        rows = await database_sync_to_async(
            lambda: list(
                SignalSpend.objects.for_team(self.team.id).values(
                    "source_id", "signal_id", "stage", "accounting_failed"
                )
            )
        )()
        assert await database_sync_to_async(
            lambda: signal_spend_totals(team_id=self.team.id, signal_ids=drivers)
        )() == {drivers[0]: 0.0246 if mode == "gateway" else 0, drivers[1]: 0.0123 if mode == "gateway" else 0}
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
        rows = await database_sync_to_async(
            lambda: list(
                SignalSpend.objects.for_team(self.team.id).values(
                    "source_id", "signal_id", "stage", "accounting_failed"
                )
            )
        )()
        if mode == "system-one-only":
            assert rows == []
        else:
            assert len(rows) == 1
            assert str(rows[0]["signal_id"]) == driver
            if request_id_available:
                assert rows[0]["source_id"] == "traditional-request"
            else:
                assert rows[0]["source_id"].startswith("unknown-")
            assert rows[0]["stage"] == "actionability"
            assert rows[0]["accounting_failed"] is (not request_id_available)
            client.messages.create.assert_awaited_once()

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

    def _set_task_cost(self, run: TaskRun, cost: int | None, *, pending: bool = False) -> None:
        run.refresh_from_db()
        state = dict(run.state or {})
        state["unprocessed_request_ids"] = ["pending-request"] if cost is None or pending else []
        if cost is not None:
            state["token_cost"] = {"model-a": {"provider-a": {"cost_microusd": cost}}}
        run.state = state
        run.save(update_fields=["state"])
        with self.captureOnCommitCallbacks(execute=True):
            task_run_cost_updated.send(sender=TaskRun, run_id=run.id, team_id=self.team.id)

    @parameterized.expand([("research",), ("repo_selection",), ("implementation",)])
    def test_late_task_cost_updates_charge_driver_once_and_preserve_fractional_cents(self, resumed_stage: str) -> None:
        driver, other = str(uuid4()), str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        research = self._run(report=report, stage=resumed_stage)
        implementation = self._run(report=report, stage="implementation")
        self._set_task_cost(research, 10_001)
        self._set_task_cost(implementation, 25_002)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5003}

        report.triggering_signal_id = other
        report.save(update_fields=["triggering_signal_id"])
        self._set_task_cost(research, 10_004)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 11.5006}
        assert SignalSpend.objects.for_team(self.team.id).count() == 2
        self.temporal.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    task_run_cost_updated.send(sender=TaskRun, run_id=research.id, team_id=self.team.id)
                    raise RuntimeError("roll back task cost")
            except RuntimeError:
                pass
        self.temporal.start_workflow.assert_not_called()

        rerun = self._run(task=research.task, stage="")
        self._set_task_cost(rerun, 1)
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver, other]) == {driver: 15.5007}
        assert SignalSpend.objects.for_team(self.team.id).get(source_id=str(rerun.id)).stage == resumed_stage

    def test_task_cost_callback_updates_spend_synchronously_without_publishing(self) -> None:
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

    @parameterized.expand(
        [
            (SignalReport.Status.CANDIDATE, None),
            (SignalReport.Status.READY, None),
            (SignalReport.Status.READY, TaskRun.Status.COMPLETED),
            (SignalReport.Status.READY, TaskRun.Status.FAILED),
            (SignalReport.Status.READY, TaskRun.Status.CANCELLED),
        ]
    )
    def test_report_publishes_at_research_or_implementation_completion(
        self, report_status: str, implementation_status: str | None
    ) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver, status=report_status)
        research = self._run(report=report)
        self._set_task_cost(research, 10_001)
        implementation = None
        if implementation_status:
            implementation = self._run(report=report, stage="implementation")
            SignalReportTask.objects.create(
                team=self.team, report=report, task_id=implementation.task_id, relationship="implementation"
            )
            self._set_task_cost(implementation, 20_002)
        async_to_sync(publish_report_spend)(team_id=self.team.id, report_id=str(report.id))
        if implementation is not None:
            self.temporal.start_workflow.assert_not_called()
            assert implementation_status is not None
            implementation.status = implementation_status
            implementation.save(update_fields=["status"])
            complete_task_spend(team_id=self.team.id, run_id=str(implementation.id))
        self.temporal.start_workflow.assert_awaited_once()
        assert self.temporal.start_workflow.call_args.args[1] == SignalSpendUpdate(
            team_id=self.team.id, signal_id=driver
        )
        self.temporal.start_workflow.return_value.result.assert_awaited_once()
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {
            driver: 11.0003 if implementation else 5.0001
        }

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
        run.state = {"ai_stage": "research", "unprocessed_request_ids": ["pending-request"], "token_cost": {}}
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["state", "status"])
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=123_456)),
        ) as fetch:
            if scout:
                complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            else:
                settle_signal_task_spend(team_id=self.team.id, signal_id=driver)
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
        self.temporal.start_workflow.assert_not_called()

    def test_one_shot_receipts_preserve_known_spend_and_record_failed_stage(self) -> None:
        driver = str(uuid4())
        for request_id, cost in [("one-shot-1", None), ("one-shot-2", 9), ("one-shot-2", None)]:
            record_llm_spend(
                request_id, token_cost_microusd=cost, team_id=self.team.id, signal_id=driver, stage="actionability"
            )
        summary = signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver]
        assert summary.total_spend == 0.0009
        assert summary.failed_stages == ["actionability"]
        for _ in range(2):
            record_llm_spend(
                "one-shot-1", token_cost_microusd=1, team_id=self.team.id, signal_id=driver, stage="actionability"
            )
        assert SignalSpend.objects.for_team(self.team.id).count() == 2
        assert signal_spend_totals(team_id=self.team.id, signal_ids=[driver]) == {driver: 0.001}
        assert signal_spend_summaries(team_id=self.team.id, signal_ids=[driver])[driver].failed_stages == []
        record_llm_spend(None, token_cost_microusd=None, team_id=self.team.id, signal_id=driver, stage="summarization")
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

    @parameterized.expand([("generation", "actionability"), ("task", "research"), ("task_cost", "task_cost_update")])
    def test_accounting_database_failure_does_not_abort_pipeline_transaction(self, source: str, stage: str) -> None:
        driver = str(uuid4())
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=driver)
        existing_run = self._run(report=report) if source == "task_cost" else None

        def fail_spend_query(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith('INSERT INTO "signals_signalspend"') or (
                source == "task_cost" and sql.startswith("SELECT") and '"signals_signalspend"' in sql
            ):
                return execute("SELECT 1 / 0", (), False, context)
            return execute(sql, params, many, context)

        with capture_logs() as logs, connection.execute_wrapper(fail_spend_query):
            if existing_run is not None:
                with self.captureOnCommitCallbacks(execute=True):
                    task_run_cost_updated.send(sender=TaskRun, run_id=existing_run.id, team_id=self.team.id)
            elif source == "task":
                run = self._run(report=report)
                assert TaskRun.objects.filter(id=run.id).exists()
            else:
                record_llm_spend(
                    "example-request",
                    token_cost_microusd=123,
                    team_id=self.team.id,
                    signal_id=driver,
                    stage="actionability",
                )
        assert SignalReport.objects.filter(id=report.id).exists()
        assert any(log["event"] == "signals.spend.accounting_failed" and log["stage"] == stage for log in logs)
