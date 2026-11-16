import json
import uuid
import asyncio
import datetime
import contextlib
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team, User
from posthog.redis import TEST_clear_clients
from posthog.token_bucket import TEST_reset_scripts

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.read import ActivitySummaryStatus, ActivitySummaryView
from products.signals.backend.models import (
    PersonalInboxRanking,
    SignalReport,
    SignalReportAssignment,
    SignalSourceConfig,
    UserActivitySummary,
    UserActivitySummaryQueueState,
)
from products.signals.backend.personal_ranking.build_budget import spend_shared_build, spend_tick_build
from products.signals.backend.personal_ranking.config import parse_config
from products.signals.backend.personal_ranking.tick import (
    STOP_ERROR_RATE,
    STOP_MAX_BUILDS_PER_DAY,
    STOP_MAX_PAIRS_PER_TICK,
    STOP_MAX_TICK_BUILDS_PER_DAY,
    STOP_TIME_BUDGET,
    PersonalRankingPairResult,
    PersonalRankingTickInput,
    PersonalRankingTickPlan,
    PersonalRankingTickResult,
    PersonalRankingTickWorkflow,
    TickPair,
    enrollment,
    is_team_enrolled,
    run_pair,
    select_pairs,
)
from products.signals.backend.personal_ranking_tasks import build_lock_key

NOW = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)
_TICK = "products.signals.backend.personal_ranking.tick"


class _TickTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tick: dict[str, Any] = {"enabled": True, "organization_ids": [str(self.organization.id)]}
        self.payload: dict[str, Any] = {}
        self.source_team_ids: set[int] = set()
        self.activity_summary_config = ActivitySummaryConfig(enabled=True, enroll_all_approved=True)
        for target, value in (
            (
                "products.signals.backend.personal_ranking.config.read_flag_payload",
                MagicMock(side_effect=lambda *_: {**self.payload, "tick": self.tick}),
            ),
            (
                f"{_TICK}.read_activity_summary_config",
                MagicMock(side_effect=lambda: self.activity_summary_config),
            ),
            (f"{_TICK}.team_ids_with_enabled_source", MagicMock(side_effect=lambda: self.source_team_ids)),
            (f"{_TICK}.has_enabled_source", MagicMock(side_effect=lambda team_id: team_id in self.source_team_ids)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _config(self):
        return parse_config({**self.payload, "tick": self.tick})

    def _pair(
        self,
        team: Team,
        email: str,
        *,
        active_hours_ago: float,
        list_hours_ago: float | None = None,
        checked_hours_ago: float | None = None,
    ) -> User:
        now = timezone.now()
        user = User.objects.create_and_join(team.organization, email, None)
        UserActivitySummary.objects.for_team(team.id).create(
            team_id=team.id, user_id=user.id, status=UserActivitySummary.Status.OK, summary={}, generated_at=now
        )
        UserActivitySummaryQueueState.objects.for_team(team.id).create(
            team_id=team.id, user_id=user.id, last_activity_at=now - datetime.timedelta(hours=active_hours_ago)
        )
        if list_hours_ago is not None:
            row = PersonalInboxRanking.objects.for_team(team.id).create(
                team_id=team.id, user_id=user.id, input_hash="old", model="m", prompt_version=1, status="ok"
            )
            PersonalInboxRanking.objects.for_team(team.id).filter(id=row.id).update(
                created_at=now - datetime.timedelta(hours=list_hours_ago),
                checked_at=None if checked_hours_ago is None else now - datetime.timedelta(hours=checked_hours_ago),
            )
        return user


class TestTickEnrollment(_TickTest):
    @parameterized.expand(
        [
            ("nothing_at_zero_without_a_list", {"organization_ids": []}, True, True, False),
            ("a_listed_organization", {}, False, True, True),
            ("a_listed_organization_without_approval", {}, False, False, False),
            ("a_denied_organization", {"deny": True}, False, True, False),
            ("a_skipped_team", {"skip": True}, False, True, False),
            ("every_team_with_a_source_at_100", {"organization_ids": [], "percentage": 100}, True, True, True),
            (
                "a_team_with_a_summary_from_the_summary_rollout",
                {"organization_ids": [], "percentage": 100, "summary_rollout": True},
                True,
                True,
                True,
            ),
            ("no_team_without_a_source_at_100", {"organization_ids": [], "percentage": 100}, False, True, False),
            ("the_tick_off", {"enabled": False}, True, True, False),
        ]
    )
    def test_enrollment(
        self, _name: str, overrides: dict[str, Any], has_source: bool, approved: bool, expected: bool
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        if has_source:
            self.source_team_ids = {self.team.id}
        if overrides.get("summary_rollout"):
            SignalSourceConfig.objects.create(
                team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
            )
            self.activity_summary_config = ActivitySummaryConfig(enabled=True, self_driving_organization_percentage=100)
        self.tick = {
            **self.tick,
            "enabled": overrides.get("enabled", True),
            "organization_ids": overrides.get("organization_ids", self.tick["organization_ids"]),
            "self_driving_organization_percentage": overrides.get("percentage", 0),
            "deny_organization_ids": [str(self.organization.id)] if overrides.get("deny") else [],
            "skip_team_ids": [self.team.id] if overrides.get("skip") else [],
        }
        config = self._config()
        self.team.refresh_from_db()

        assert (enrollment(config).team_ids, is_team_enrolled(config, self.team)) == (
            [self.team.id] if expected else [],
            expected,
        )


class TestTickSelection(_TickTest):
    def test_selects_overdue_pairs_first_then_paying_and_recent_activity_within_the_org_share(self) -> None:
        paying = Team.objects.create(
            organization=Organization.objects.create(name="Paying", has_active_subscription=True), name="Paying"
        )
        free = Team.objects.create(organization=Organization.objects.create(name="Free"), name="Free")
        with time_machine.travel(NOW, tick=False):
            users = {
                "paying_recent": self._pair(paying, "paying@example.com", active_hours_ago=0.5, list_hours_ago=2),
                "free_no_list": self._pair(free, "a@example.com", active_hours_ago=30),
                "free_overdue": self._pair(free, "b@example.com", active_hours_ago=10, list_hours_ago=6),
                # Past this organization's share of the tick.
                "free_recent": self._pair(free, "c@example.com", active_hours_ago=1, list_hours_ago=3),
                "old_activity_overdue": self._pair(self.team, "d@example.com", active_hours_ago=20, list_hours_ago=30),
                # Past the limit: the most recent activity does not beat an overdue pair.
                "recent_not_overdue": self._pair(self.team, "e@example.com", active_hours_ago=0.2, list_hours_ago=1.5),
                "fresh_list": self._pair(self.team, "f@example.com", active_hours_ago=1, list_hours_ago=0.2),
                "checked_recently": self._pair(
                    self.team, "g@example.com", active_hours_ago=1, list_hours_ago=30, checked_hours_ago=0.2
                ),
                "inactive": self._pair(self.team, "h@example.com", active_hours_ago=24 * 10),
            }
            selection = select_pairs(
                parse_config({"tick": {"enabled": True, "max_org_share": 0.5, "overdue_after_minutes": 240}}),
                NOW,
                4,
                [paying.id, free.id, self.team.id],
            )

        assert [pair.user_id for pair in selection.pairs] == [
            users[name].id for name in ("free_no_list", "old_activity_overdue", "free_overdue", "paying_recent")
        ]
        assert (selection.due_pairs, selection.due_without_list, selection.oldest_due_hours) == (6, 1, 30.0)
        assert (selection.due_overdue, selection.picked_overdue) == (3, 3)
        assert (selection.oldest_due_activity_hours, selection.oldest_due_summary_hours) == (20.0, 0.0)
        assert selection.fresh_share == 2 / 8
        assert (selection.pair_list_hours, selection.unpicked_without_list, selection.unpicked_oldest_hours) == (
            [None, 30.0, 6.0, 2.0],
            0,
            3.0,
        )


class TestTickPair(_TickTest):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        TEST_reset_scripts()
        cache.delete(build_lock_key(self.team.id, self.user.id))
        self.malformed_answers = 0
        self.llm = MagicMock()
        self.create = self.llm.with_options.return_value.chat.completions.create
        self.create.side_effect = lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=self._answer()))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        scoped_capture = MagicMock()
        self.capture = scoped_capture.return_value.__enter__.return_value
        summary = ActivitySummaryView(status=ActivitySummaryStatus.READY, version=1)
        for target, value in (
            ("products.signals.backend.personal_ranking.logic.build_openai_client", MagicMock(return_value=self.llm)),
            ("products.signals.backend.personal_ranking.logic.get_summary", MagicMock(return_value=summary)),
            ("products.signals.backend.personal_ranking.logic.ph_scoped_capture", scoped_capture),
            (
                "products.signals.backend.personal_ranking.candidates.fetch_source_products_for_reports",
                MagicMock(return_value={}),
            ),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        report = SignalReport.objects.create(
            team=self.team, title="Claimed", summary="Claimed", signal_count=1, total_weight=1.0, status="ready"
        )
        SignalReportAssignment.all_teams.create(team=self.team, report=report, actor_kind="user", actor_user=self.user)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            status=UserActivitySummary.Status.OK,
            summary={},
            generated_at=timezone.now(),
        )
        UserActivitySummaryQueueState.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, last_activity_at=timezone.now()
        )

    def _answer(self) -> str:
        if self.malformed_answers:
            self.malformed_answers -= 1
            return "not json"
        return json.dumps(
            {
                "ranked": [{"ref": "c1", "rank": 1, "tier": "top", "reason": "r", "matched": None, "next_step": None}],
                "folded": [],
            }
        )

    def _run(self) -> PersonalRankingPairResult:
        return run_pair(TickPair(team_id=self.team.id, user_id=self.user.id))

    def _rows(self):
        return PersonalInboxRanking.objects.for_team(self.team.id).filter(user_id=self.user.id)

    @parameterized.expand(
        [
            ("a_ranked_list_is_kept", 0, "built", "unchanged", 1),
            ("a_failed_model_call_is_retried", 1, "failed", "built", 2),
        ]
    )
    def test_an_unchanged_pair_calls_no_model_unless_its_last_build_failed(
        self, _name: str, malformed_answers: int, first: str, second: str, model_calls: int
    ) -> None:
        self.malformed_answers = malformed_answers
        assert self._run() == PersonalRankingPairResult(
            status=first,  # type: ignore[arg-type]
            model_called=True,
            changed_parts=["no_previous_list"],
        )
        assert self.capture.call_args.kwargs["properties"]["trigger"] == "tick"
        self._rows().update(created_at=timezone.now() - datetime.timedelta(hours=2))
        assert len(select_pairs(self._config(), timezone.now(), 10, [self.team.id]).pairs) == 1

        assert self._run() == PersonalRankingPairResult(
            status=second,  # type: ignore[arg-type]
            model_called=second == "built",
        )
        if second == "built":
            # The retried build has the inputs of the failed one, so it reads the stored parts and finds no change.
            assert self.capture.call_args.kwargs["properties"]["changed_parts"] == []

        assert self.create.call_count == model_calls
        assert select_pairs(self._config(), timezone.now(), 10, [self.team.id]).pairs == []

    @parameterized.expand([("running",), ("tick_limited",), ("shared_limited",), ("not_enrolled",)])
    def test_a_pair_that_may_not_build_calls_no_model(self, status: str) -> None:
        self.payload = {"max_builds_per_day": 1}
        self.tick = {**self.tick, "max_tick_builds_per_day": 1}
        if status == "running":
            cache.add(build_lock_key(self.team.id, self.user.id), "1")
        elif status == "tick_limited":
            assert spend_tick_build(self._config())
        elif status == "shared_limited":
            assert spend_shared_build(self._config()) is None
        else:
            self.tick = {**self.tick, "organization_ids": []}

        assert self._run() == PersonalRankingPairResult(status=status)  # type: ignore[arg-type]

        assert (self.create.call_count, self._rows().count()) == (0, 0)
        if status == "shared_limited":
            # The tick's own limit gets its build back.
            assert spend_tick_build(self._config())


def _plan(pairs: int, **overrides: Any) -> PersonalRankingTickPlan:
    fields: dict[str, Any] = {
        "enabled": True,
        "pairs": [TickPair(team_id=1, user_id=user_id) for user_id in range(pairs)],
        # The first pair has no list, and pair `n` has a list `n` hours old.
        "pair_list_hours": [None, *(float(hours) for hours in range(1, pairs))],
        "max_concurrency": 2,
        "max_error_rate": 0.5,
        "time_budget_seconds": 600.0,
        "stop_reason": None,
        "due_pairs": pairs,
        "due_overdue": pairs,
        "picked_overdue": 2,
        "enrolled_teams": 3,
    }
    return PersonalRankingTickPlan(**{**fields, **overrides})


async def _run_tick(
    plan: PersonalRankingTickPlan,
    pair_status: str | Callable[[TickPair], Awaitable[str]],
    *,
    sliding_window: bool = True,
) -> tuple[PersonalRankingTickResult, int, list[PersonalRankingTickResult]]:
    running = peak = 0
    captured: list[PersonalRankingTickResult] = []

    @activity.defn(name="plan_personal_ranking_tick_activity")
    async def fake_plan(input: PersonalRankingTickInput) -> PersonalRankingTickPlan:
        return plan

    @activity.defn(name="build_personal_ranking_pair_activity")
    async def fake_pair(pair: TickPair) -> PersonalRankingPairResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        if isinstance(pair_status, str):
            status = pair_status
            await asyncio.sleep(0.01)
        else:
            status = await pair_status(pair)
        running -= 1
        return PersonalRankingPairResult(
            status=status,  # type: ignore[arg-type]
            model_called=status in ("built", "failed"),
            changed_parts=["scores", "needs_you"] if status == "built" else [],
        )

    @activity.defn(name="capture_personal_ranking_tick_activity")
    async def fake_capture(result: PersonalRankingTickResult) -> None:
        captured.append(result)

    original_patched = workflow.patched

    def patched(patch_id: str) -> bool:
        return sliding_window and original_patched(patch_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="personal-ranking-tick-test",
            workflows=[PersonalRankingTickWorkflow],
            activities=[fake_plan, fake_pair, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with patch.object(workflow, "patched", patched):
                handle = await env.client.start_workflow(
                    PersonalRankingTickWorkflow.run,
                    PersonalRankingTickInput(),
                    id=f"personal-ranking-tick-{uuid.uuid4()}",
                    task_queue="personal-ranking-tick-test",
                )
                result = await handle.result()
            history = await handle.fetch_history()
    # A tick that runs during a deploy replays its history on the new code.
    await Replayer(
        workflows=[PersonalRankingTickWorkflow], workflow_runner=UnsandboxedWorkflowRunner()
    ).replay_workflow(history)
    return result, peak, captured


@pytest.mark.asyncio
@pytest.mark.parametrize("sliding_window", [True, False])
@pytest.mark.parametrize(
    "plan,pair_status,picked,stop_reason,remaining",
    [
        (_plan(5), "built", 5, None, (0, 0, None)),
        (_plan(5), "unchanged", 5, None, (0, 0, None)),
        # The pairs running when the limit refused a build finish, and no later pair starts.
        (_plan(5), "tick_limited", 2, STOP_MAX_TICK_BUILDS_PER_DAY, (5, 1, 4.0)),
        (_plan(5), "shared_limited", 2, STOP_MAX_BUILDS_PER_DAY, (5, 1, 4.0)),
        # The breaker waits for a sample of 10 model calls.
        (_plan(20, max_concurrency=1), "failed", 10, STOP_ERROR_RATE, (20, 1, 19.0)),
        (_plan(5, time_budget_seconds=0.0), "built", 0, STOP_TIME_BUDGET, (5, 1, 4.0)),
        # The due pairs past the per-tick cap stay in the backlog after every picked pair is built.
        (
            _plan(
                5,
                due_pairs=8,
                stop_reason=STOP_MAX_PAIRS_PER_TICK,
                unpicked_without_list=2,
                unpicked_oldest_hours=30.0,
            ),
            "built",
            5,
            STOP_MAX_PAIRS_PER_TICK,
            (3, 2, 30.0),
        ),
        # A tick planned before a deploy replays with a plan that has no list ages.
        (_plan(5, pair_list_hours=[]), "built", 5, None, None),
    ],
)
async def test_the_tick_bounds_concurrency_and_stops_at_each_limit(
    plan: PersonalRankingTickPlan,
    pair_status: str,
    picked: int,
    stop_reason: str | None,
    remaining: tuple[int, int, float | None] | None,
    sliding_window: bool,
) -> None:
    result, peak, captured = await _run_tick(plan, pair_status, sliding_window=sliding_window)

    assert peak <= plan.max_concurrency
    assert (result.picked, result.statuses, result.stop_reason) == (
        picked,
        {pair_status: picked} if picked else {},
        stop_reason,
    )
    assert (result.due_pairs, result.enrolled_teams) == (plan.due_pairs, plan.enrolled_teams)
    assert (result.due_overdue, result.picked_overdue) == (plan.due_overdue, min(picked, 2))
    backlog = result.remaining
    # The tick takes a few milliseconds, which adds to the age of the oldest remaining list.
    assert (
        None
        if backlog is None
        else (
            backlog.due_pairs,
            backlog.due_without_list,
            None if backlog.oldest_due_hours is None else round(backlog.oldest_due_hours, 2),
        )
    ) == remaining
    assert result.changed_parts == (
        {"scores": picked, "needs_you": picked} if pair_status == "built" and picked else {}
    )
    timed = sliding_window and picked and pair_status in ("built", "unchanged")
    assert (set(result.pair_seconds_p50), set(result.pair_seconds_p95)) == (
        {pair_status} if timed else set(),
        {pair_status} if timed else set(),
    )
    assert captured == [result]


@pytest.mark.asyncio
async def test_fast_pairs_start_while_a_slow_pair_runs() -> None:
    fast_done = asyncio.Event()
    finished: list[int] = []

    async def pair_status(pair: TickPair) -> str:
        if pair.user_id == 0:
            # A wave loop never starts the fast pairs behind this one, so the wait times out.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(fast_done.wait(), timeout=5)
            finished.append(pair.user_id)
            return "built"
        await asyncio.sleep(0.01)
        finished.append(pair.user_id)
        if len(finished) == 4:
            fast_done.set()
        return "unchanged"

    result, peak, _ = await _run_tick(_plan(5), pair_status)

    assert finished[-1] == 0
    assert (result.picked, result.statuses, result.stop_reason, peak) == (
        5,
        {"built": 1, "unchanged": 4},
        None,
        2,
    )


@pytest.mark.asyncio
async def test_a_disabled_tick_runs_no_pair() -> None:
    result, peak, captured = await _run_tick(_plan(0, enabled=False), "built")

    assert (result, peak, captured) == (PersonalRankingTickResult(), 0, [])
