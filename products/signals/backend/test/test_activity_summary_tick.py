import json
import uuid
import asyncio
import datetime
import dataclasses
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from temporalio import activity
from temporalio.client import Client, ScheduleState
from temporalio.converter import DataConverter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import ActivityLog, Organization, Team, User

from products.signals.backend.activity_summary import (
    schedule as tick_schedule,
    tick,
)
from products.signals.backend.activity_summary.config import ActivitySummaryConfig, parse_config
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION
from products.signals.backend.activity_summary.queue import (
    ActivitySummaryPair,
    DailyUsage,
    daily_usage,
    max_update_cost_usd,
    select_pairs,
)
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, MAX_LIMITS, RENDER_VERSION, RenderLimits
from products.signals.backend.activity_summary.schedule import (
    ACTIVITY_SUMMARY_TICK_SCHEDULE_ID,
    create_activity_summary_tick_schedule,
)
from products.signals.backend.activity_summary.tick import (
    STOP_GATEWAY_NOT_CONFIGURED,
    STOP_MAX_COST_USD_PER_DAY,
    STOP_MAX_PAIRS_PER_DAY,
    STOP_MAX_PAIRS_PER_TICK,
    ActivitySummaryPairInput,
    ActivitySummaryPairResult,
    ActivitySummaryTickInput,
    ActivitySummaryTickPlan,
    ActivitySummaryTickResult,
    ActivitySummaryTickWorkflow,
    plan_tick,
    run_pair,
)
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.test.test_activity_summary_render import FakeLLM
from products.tasks.backend.facade.user_task_summaries import UserTaskTime

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
ANSWER = json.dumps(
    {
        "profile": "## Funnels\n- Builds the signup funnel.",
        "headline": "Builds the signup funnel.",
        "focus_areas": [{"topic": "signup funnel", "strength": "high", "last_seen": "2026-10-18"}],
        "products": ["product_analytics"],
        "recent_shift": None,
    }
)


_CONFIG_CASES: list[tuple[str, Any, ActivitySummaryConfig]] = [
    ("no payload", None, ActivitySummaryConfig()),
    ("not an object", "[1, 2]", ActivitySummaryConfig()),
    ("enabled is missing", {"organization_ids": ["a"]}, ActivitySummaryConfig()),
    ("enabled is not a bool", {"enabled": "true"}, ActivitySummaryConfig()),
    ("enabled with defaults", {"enabled": True}, ActivitySummaryConfig(enabled=True)),
    (
        "invalid fields fall back to the defaults",
        {
            "enabled": True,
            "organization_ids": ["org-a", 7, ""],
            "skip_team_ids": [3, "4", True],
            "max_pairs_per_tick": 0,
            "max_pairs_per_day": True,
            "max_cost_usd_per_day": -1,
            "max_concurrency": "8",
            "min_units": None,
            "min_update_interval_hours": 0,
            "emit_embeddings": "no",
            "rebuild_before": "not a time",
        },
        ActivitySummaryConfig(enabled=True, organization_ids=("org-a",), skip_team_ids=(3,)),
    ),
    (
        "valid fields",
        {
            "enabled": True,
            "max_pairs_per_tick": 5,
            "max_cost_usd_per_day": 1,
            "min_update_interval_hours": 12,
            "capture_events": False,
            "rebuild_before": "2026-10-01T00:00:00",
        },
        ActivitySummaryConfig(
            enabled=True,
            max_pairs_per_tick=5,
            max_cost_usd_per_day=1.0,
            min_update_interval_hours=12.0,
            capture_events=False,
            rebuild_before=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
        ),
    ),
    (
        "limits fall back to the defaults when invalid and clamp when too large",
        {
            "enabled": True,
            "limits": {
                "task_lines": 20,
                "activity_lines": 0,
                "max_units_per_day": True,
                "sections_max_chars": "9000",
                "window_days": 10_000,
                "max_completion_tokens": 10_000_000,
            },
        },
        ActivitySummaryConfig(
            enabled=True, limits=RenderLimits(task_lines=20, window_days=90, max_completion_tokens=16000)
        ),
    ),
    ("limits that are not an object", {"enabled": True, "limits": [5]}, ActivitySummaryConfig(enabled=True)),
    (
        "a future rebuild_before waits",
        {"enabled": True, "rebuild_before": "2026-10-20T00:00:00+00:00"},
        ActivitySummaryConfig(enabled=True),
    ),
]


@parameterized.expand(_CONFIG_CASES)
@time_machine.travel(NOW, tick=False)
def test_parse_config(_name: str, payload: Any, expected: ActivitySummaryConfig) -> None:
    assert parse_config(payload) == expected


@time_machine.travel(NOW, tick=False)
class TestActivitySummaryQueue(BaseTest):
    def _config(self, **overrides: Any) -> ActivitySummaryConfig:
        return ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),), **overrides)

    def _user(self, email: str) -> User:
        return User.objects.create_and_join(self.organization, email, None)

    def _changes(self, user: User, count: int, *, days_ago: float = 1, team: Team | None = None, **fields: Any):
        for index in range(count):
            ActivityLog.objects.create(
                team_id=(team or self.team).id,
                organization_id=self.organization.id,
                user=user,
                scope="Insight",
                activity="created",
                item_id=str(index),
                detail={"name": f"Funnel {index}"},
                created_at=NOW - datetime.timedelta(days=days_ago + index / 100),
                **fields,
            )

    def _summary(self, user: User, **fields: Any) -> None:
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=user.id,
            status=UserActivitySummary.Status.OK,
            **({"prompt_version": PROMPT_VERSION, "render_version": RENDER_VERSION} | fields),
        )

    def _select(self, config: ActivitySummaryConfig | None = None, tasks: list[UserTaskTime] | None = None):
        with patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=tasks or []):
            return [(pair.team_id, pair.user_id) for pair in select_pairs(config or self._config(), NOW, 10)]

    def test_orders_cold_starts_then_most_new_rows_then_oldest_summary(self) -> None:
        stale, fresh, busy, cold = (self._user(f"{name}@example.com") for name in ("stale", "fresh", "busy", "cold"))
        self._summary(
            stale, generated_at=NOW - datetime.timedelta(days=5), input_watermark=NOW - datetime.timedelta(days=3)
        )
        self._summary(
            fresh, generated_at=NOW - datetime.timedelta(days=2), input_watermark=NOW - datetime.timedelta(days=3)
        )
        self._summary(
            busy, generated_at=NOW - datetime.timedelta(days=1), input_watermark=NOW - datetime.timedelta(days=3)
        )
        self._changes(stale, 1)
        self._changes(fresh, 1)
        # Rows at or before the watermark are not new.
        self._changes(busy, 2, days_ago=4)
        self._changes(busy, 2)
        self._changes(cold, 1)
        tasks = [UserTaskTime(team_id=self.team.id, user_id=busy.id, created_at=NOW - datetime.timedelta(hours=1))]

        assert self._select(tasks=tasks) == [
            (self.team.id, cold.id),
            (self.team.id, busy.id),
            (self.team.id, stale.id),
            (self.team.id, fresh.id),
        ]

    def test_a_stale_summary_is_due_without_new_rows_and_ranks_with_cold_starts(self) -> None:
        current, old_version, before_rebuild, busy = (
            self._user(f"{name}@example.com") for name in ("current", "old", "rebuild", "busy")
        )
        summary_fields = {
            "generated_at": NOW - datetime.timedelta(days=2),
            "input_watermark": NOW - datetime.timedelta(days=2),
        }
        self._summary(current, **summary_fields)
        self._summary(old_version, **(summary_fields | {"prompt_version": PROMPT_VERSION - 1}))
        self._summary(before_rebuild, **(summary_fields | {"generated_at": NOW - datetime.timedelta(days=3)}))
        self._summary(busy, **summary_fields)
        for user in (current, old_version, before_rebuild):
            self._changes(user, 1, days_ago=5)
        self._changes(busy, 3)

        config = self._config(rebuild_before=NOW - datetime.timedelta(days=2, hours=12))
        assert self._select(config) == [
            (self.team.id, before_rebuild.id),
            (self.team.id, old_version.id),
            (self.team.id, busy.id),
        ]

    def test_leaves_out_pairs_that_are_not_due_or_not_enrolled(self) -> None:
        waiting, scout_only, impersonated, skipped_team = (
            self._user(f"{name}@example.com") for name in ("waiting", "scout", "impersonated", "skipped")
        )
        due = self._user("due@example.com")
        self._summary(waiting, next_eligible_at=NOW + datetime.timedelta(hours=1))
        self._changes(waiting, 3)
        self._changes(scout_only, 3, client="scout:product-analytics")
        self._changes(impersonated, 3, was_impersonated=True)
        other_team = Team.objects.create(organization=self.organization, name="Skipped")
        self._changes(skipped_team, 3, team=other_team)
        self._changes(due, 3)
        other_org = Organization.objects.create(name="Not enrolled")
        self._changes(due, 3, team=Team.objects.create(organization=other_org, name="Other"))

        assert self._select(self._config(skip_team_ids=(other_team.id,))) == [(self.team.id, due.id)]

    def test_selects_nothing_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self._changes(self.user, 3)

        assert self._select() == []

    def test_daily_usage_counts_model_calls_and_prices_a_missing_cost_at_the_bound(self) -> None:
        priced, unpriced, skipped = (self._user(f"{name}@example.com") for name in ("priced", "unpriced", "skipped"))
        self._summary(priced, cost_usd=0.25)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=unpriced.id, status=UserActivitySummary.Status.FAILED
        )
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=skipped.id, status=UserActivitySummary.Status.SKIPPED
        )

        usage = daily_usage(NOW)

        assert usage.updates == 2
        assert usage.cost_usd == pytest.approx(0.25 + max_update_cost_usd(MAX_LIMITS))
        with time_machine.travel(NOW + datetime.timedelta(days=1, minutes=1), tick=False):
            assert daily_usage(NOW + datetime.timedelta(days=1, minutes=1)).updates == 0

    @parameterized.expand(
        [
            ("the tick cap", {"max_pairs_per_tick": 1}, "phs_test", STOP_MAX_PAIRS_PER_TICK, 1),
            ("the daily pair cap", {"max_pairs_per_day": 1}, "phs_test", STOP_MAX_PAIRS_PER_DAY, 0),
            ("the daily cost cap", {"max_cost_usd_per_day": 0.1}, "phs_test", STOP_MAX_COST_USD_PER_DAY, 0),
            ("no cap", {}, "phs_test", None, 2),
            ("no gateway", {}, "", STOP_GATEWAY_NOT_CONFIGURED, 0),
        ]
    )
    def test_plan_names_the_cap_that_stops_it(
        self, _name: str, overrides: dict[str, Any], gateway_key: str, stop_reason: str | None, pairs: int
    ) -> None:
        self._changes(self._user("a@example.com"), 3)
        self._changes(self._user("b@example.com"), 3)
        self._summary(self.user, cost_usd=0.1)

        with (
            override_settings(
                AI_GATEWAY_URL="https://ai-gateway.example/v1" if gateway_key else "",
                AI_GATEWAY_API_KEY=gateway_key,
                LLM_GATEWAY_URL="",
                LLM_GATEWAY_API_KEY="",
            ),
            patch.object(tick, "read_config", return_value=self._config(**overrides)),
            patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=[]),
        ):
            plan = plan_tick(None, NOW)

        assert (plan.stop_reason, len(plan.pairs), plan.enabled) == (stop_reason, pairs, bool(gateway_key))

    @parameterized.expand(
        [
            ("too few units", 2, {"return_value": FakeLLM([ANSWER])}, False, "skipped_too_few_units", False),
            (
                "an exception before the model call",
                3,
                {"side_effect": RuntimeError("no gateway")},
                False,
                "failed",
                False,
            ),
            ("an exception after the model call", 3, {"return_value": FakeLLM([ANSWER])}, True, "failed", True),
        ]
    )
    def test_a_pair_that_raised_or_skipped_does_not_come_back_on_the_next_tick(
        self, _name: str, changes: int, gateway: dict[str, Any], store_fails: bool, status: str, called_model: bool
    ) -> None:
        self._changes(self.user, changes)
        pair_input = ActivitySummaryPairInput(
            team_id=self.team.id,
            user_id=self.user.id,
            min_units=3,
            min_update_interval_hours=24,
            emit_embeddings=True,
            capture_events=True,
        )
        assert self._select() == [(self.team.id, self.user.id)]

        with (
            patch("products.signals.backend.activity_summary.logic.gateway_client", **gateway),
            patch(
                "products.signals.backend.activity_summary.logic.summary_text",
                side_effect=RuntimeError("store failed") if store_fails else None,
                return_value="summary",
            ),
        ):
            result = run_pair(pair_input)

        assert (result.status, result.called_model) == (status, called_model)
        assert self._select() == []
        if called_model:
            assert result.cost_usd
            usage = daily_usage(NOW)
            assert usage.updates == 1
            assert usage.cost_usd == pytest.approx(result.cost_usd)
        else:
            assert daily_usage(NOW) == DailyUsage(updates=0, cost_usd=0.0)

    def test_an_exception_before_the_model_call_keeps_an_earlier_paid_update_in_the_daily_caps(self) -> None:
        self._changes(self.user, 3)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, status=UserActivitySummary.Status.FAILED, cost_usd=0.25
        )

        with patch(
            "products.signals.backend.activity_summary.logic.gateway_client", side_effect=RuntimeError("no gateway")
        ):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=True,
                    capture_events=True,
                )
            )

        assert (result.status, result.called_model) == ("failed", False)
        assert self._select() == []
        assert daily_usage(NOW) == DailyUsage(updates=1, cost_usd=0.25)

    def test_an_ok_update_emits_the_embedding_and_an_event_without_the_summary(self) -> None:
        self._changes(self.user, 3)
        capture = MagicMock()
        with (
            patch("products.signals.backend.activity_summary.logic.gateway_client", return_value=FakeLLM([ANSWER])),
            patch("posthog.api.embedding_worker.emit_embedding_request") as emit,
            patch.object(tick, "ph_background_capture", return_value=capture),
        ):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=True,
                    capture_events=True,
                )
            )

        assert (result.status, result.called_model) == ("ok", True)
        assert emit.call_args.kwargs["document_id"] == f"{self.user.id}:2026-10-19"
        assert emit.call_args.kwargs["content"] == "Builds the signup funnel.\nFocus areas: signup funnel"
        event = capture.call_args.kwargs
        assert event["event"] == "activity summary generated"
        assert "signup funnel" not in json.dumps(event["properties"]).lower()


@pytest.mark.asyncio
async def test_an_update_keeps_an_operator_pause() -> None:
    client = MagicMock(spec=Client)
    state = ScheduleState(paused=True, note="Paused by an operator")
    client.get_schedule_handle.return_value.describe = AsyncMock(
        return_value=MagicMock(schedule=MagicMock(state=state))
    )
    with (
        patch.object(tick_schedule, "a_schedule_exists", return_value=True),
        patch.object(tick_schedule, "a_create_schedule") as create,
        patch.object(tick_schedule, "a_update_schedule") as update,
    ):
        await create_activity_summary_tick_schedule(client)

    create.assert_not_awaited()
    client.get_schedule_handle.assert_called_once_with(ACTIVITY_SUMMARY_TICK_SCHEDULE_ID)
    assert update.await_args is not None
    assert update.await_args.args[2].state == state


def _plan(pairs: int, **overrides: Any) -> ActivitySummaryTickPlan:
    fields: dict[str, Any] = {
        "enabled": True,
        "pairs": [ActivitySummaryPair(team_id=1, user_id=user_id) for user_id in range(pairs)],
        "candidates": pairs,
        "updates_left": 100,
        "cost_left_usd": 100.0,
        "max_update_cost_usd": 1.0,
        "max_concurrency": 2,
        "min_units": 3,
        "min_update_interval_hours": 24.0,
        "emit_embeddings": True,
        "capture_events": True,
        "limits": DEFAULT_LIMITS,
        "stop_reason": None,
    }
    return ActivitySummaryTickPlan(**{**fields, **overrides})


async def _run_tick(
    plan: ActivitySummaryTickPlan, pair_cost: float | None
) -> tuple[ActivitySummaryTickResult, int, list[ActivitySummaryTickResult]]:
    running = peak = 0
    captured: list[ActivitySummaryTickResult] = []

    @activity.defn(name="plan_activity_summary_tick_activity")
    async def fake_plan(input: ActivitySummaryTickInput) -> ActivitySummaryTickPlan:
        return plan

    @activity.defn(name="update_activity_summary_pair_activity")
    async def fake_pair(input: ActivitySummaryPairInput) -> ActivitySummaryPairResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return ActivitySummaryPairResult(status="ok", cost_usd=pair_cost, called_model=True)

    @activity.defn(name="capture_activity_summary_tick_activity")
    async def fake_capture(result: ActivitySummaryTickResult) -> None:
        captured.append(result)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="activity-summary-tick-test",
            workflows=[ActivitySummaryTickWorkflow],
            activities=[fake_plan, fake_pair, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ActivitySummaryTickWorkflow.run,
                ActivitySummaryTickInput(),
                id=f"activity-summary-tick-{uuid.uuid4()}",
                task_queue="activity-summary-tick-test",
            )
    return result, peak, captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,pair_cost,picked,stop_reason",
    [
        (_plan(5), 0.01, 5, None),
        (_plan(5, updates_left=3), 0.01, 3, STOP_MAX_PAIRS_PER_DAY),
        # A missing cost counts at the bound, so the second wave spends the last of the budget.
        (_plan(6, cost_left_usd=3.0), None, 4, STOP_MAX_COST_USD_PER_DAY),
    ],
)
async def test_the_tick_bounds_concurrency_and_stops_at_the_daily_caps(
    plan: ActivitySummaryTickPlan, pair_cost: float | None, picked: int, stop_reason: str | None
) -> None:
    result, peak, captured = await _run_tick(plan, pair_cost)

    assert peak <= plan.max_concurrency
    assert (result.picked, result.statuses, result.stop_reason) == (picked, {"ok": picked}, stop_reason)
    assert captured == [result]


@pytest.mark.asyncio
async def test_a_disabled_tick_runs_no_pair() -> None:
    result, peak, captured = await _run_tick(_plan(0, enabled=False), 0.01)

    assert (result, peak, captured) == (ActivitySummaryTickResult(), 0, [])


@parameterized.expand(
    [
        ("tick plan", ActivitySummaryTickPlan, lambda: _plan(1)),
        (
            "pair input",
            ActivitySummaryPairInput,
            lambda: ActivitySummaryPairInput(
                team_id=1,
                user_id=2,
                min_units=3,
                min_update_interval_hours=24.0,
                emit_embeddings=True,
                capture_events=True,
            ),
        ),
    ]
)
def test_a_payload_recorded_before_limits_existed_decodes_with_the_default_limits(
    _name: str, cls: type, build: Any
) -> None:
    converter = DataConverter.default.payload_converter
    recorded = {key: value for key, value in dataclasses.asdict(build()).items() if key != "limits"}

    [decoded] = converter.from_payloads(converter.to_payloads([recorded]), [cls])

    assert decoded == build()
    assert decoded.limits == DEFAULT_LIMITS
