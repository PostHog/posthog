import uuid
import datetime as dt
import dataclasses

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async

# Private, but it's the only signal an activity uses to say "I'll be completed asynchronously".
from temporalio.activity import _CompleteAsyncError
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope
from posthog.slo.types import SloArea, SloConfig, SloOperation

from products.pulse.backend.agent.mission import build_general_brief_mission
from products.pulse.backend.agent.sandbox_run import MissionRunResult, ReportTooLargeError
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind
from products.pulse.backend.temporal.activities import (
    MAX_ITEMS,
    cleanup_orphaned_sandbox_activity,
    finalize_agent_activity,
    gather_brief_inputs_activity,
    launch_agent_activity,
    prepare_mission_activity,
    resolve_period,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.inputs import (
    CleanupSandboxInputs,
    FinalizeAgentInputs,
    GenerateBriefWorkflowInputs,
    LaunchAgentInputs,
    SynthesizeActivityInputs,
)
from products.pulse.backend.temporal.registry import ACTIVITIES
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class _StubSource:
    name = "stub"

    def gather(self, team, config, lookback_days) -> list[SourceItem]:
        return [
            SourceItem(
                source="stub",
                kind=SourceItemKind.MOVEMENT,
                title="Pageviews dropped 30%",
                description="d",
                metrics={"pct_change": -30.0},
                evidence=[
                    EvidenceRef(type=EvidenceType.INSIGHT, ref="abc", label="Pageviews", url="/project/1/insights/abc")
                ],
                fingerprint_hint="abc:0",
            )
        ]


class _RaisingSource:
    name = "raising"

    def gather(self, team, config, lookback_days) -> list[SourceItem]:
        raise RuntimeError("db exploded")


class _EmptySource:
    name = "empty"

    def gather(self, team, config, lookback_days) -> list[SourceItem]:
        return []


class _ManyItemsSource:
    def __init__(self, kind: str, count: int) -> None:
        self.name = f"many_{kind}"
        self._kind = SourceItemKind(kind)
        self._count = count

    def gather(self, team, config, lookback_days) -> list[SourceItem]:
        return [
            SourceItem(source=self.name, kind=self._kind, title=f"{self._kind} {i}", description="d")
            for i in range(self._count)
        ]


@sync_to_async
def _set_ai_consent(team, approved: bool) -> None:
    team.organization.is_ai_data_processing_approved = approved
    team.organization.save()


@sync_to_async
def _create_brief(team, user) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(team=team, created_by=user, trigger=ProductBrief.Trigger.ON_DEMAND)


@sync_to_async
def _create_userless_brief(team) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(team=team, created_by=None, trigger=ProductBrief.Trigger.SCHEDULED)


@sync_to_async
def _create_brief_with_goal(team, user, goal: str) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        config = BriefConfig.objects.create(team=team, name="cfg", goal=goal)
        return ProductBrief.objects.create(
            team=team, created_by=user, config=config, trigger=ProductBrief.Trigger.ON_DEMAND
        )


@sync_to_async
def _reload_brief(brief_id) -> ProductBrief:
    return ProductBrief.objects.unscoped().get(id=brief_id)


@sync_to_async
def _opportunity_count(team) -> int:
    return Opportunity.objects.for_team(team.pk).count()


def _confident_out() -> BriefOut:
    return BriefOut(
        sections=[BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["c1"], confidence=0.9)],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=["c1"],
                fingerprint_hint="abc:0",
                confidence=0.9,
                goal_relevant=False,
            )
        ],
    )


async def test_gather_activity_returns_serialized_items(team) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=[_StubSource()]):
        items = await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None),
        )
    assert len(items) == 1
    assert items[0]["fingerprint_hint"] == "abc:0"


async def test_gather_activity_refuses_without_ai_consent(team) -> None:
    await _set_ai_consent(team, False)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None),
        )
    assert exc_info.value.non_retryable is True


async def test_prepare_mission_returns_seeds_and_pins_window(team, user) -> None:
    await _set_ai_consent(team, True)
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=[_StubSource()]):
        bundle = await env.run(
            prepare_mission_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id=str(brief.id)),
        )
    assert bundle["mission"] == "general_brief"
    assert bundle["brief_id"] == str(brief.id)
    assert [item["fingerprint_hint"] for item in bundle["seed_items"]] == ["abc:0"]
    assert [grant["name"] for grant in bundle["tool_grants"]] == ["posthog"]
    reloaded = await _reload_brief(brief.id)
    assert reloaded.window_start is not None and reloaded.window_end is not None
    assert reloaded.window_end - reloaded.window_start == dt.timedelta(days=7)


async def test_prepare_mission_returns_empty_seeds_when_sources_are_quiet(team, user) -> None:
    await _set_ai_consent(team, True)
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=[]):
        bundle = await env.run(
            prepare_mission_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id=str(brief.id)),
        )
    assert bundle["seed_items"] == []
    reloaded = await _reload_brief(brief.id)
    assert reloaded.window_start is not None and reloaded.window_end is not None


async def test_prepare_mission_refuses_without_ai_consent(team, user) -> None:
    await _set_ai_consent(team, False)
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            prepare_mission_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id=str(brief.id)),
        )
    assert exc_info.value.non_retryable is True


@sync_to_async
def _bundle_dict(team, brief) -> dict:
    window_end = dt.datetime(2026, 7, 8, 12, tzinfo=dt.UTC)
    return build_general_brief_mission(
        team=team,
        brief=brief,
        config=None,
        items=[],
        window_start=window_end - dt.timedelta(days=7),
        window_end=window_end,
        lookback_days=7,
    ).model_dump(mode="json")


async def test_launch_agent_activity_stashes_completion_context_and_completes_async(team, user) -> None:
    brief = await _create_brief(team, user)
    bundle = await _bundle_dict(team, brief)
    env = ActivityEnvironment()

    # The real activity passes an on_sandbox_created hook into launch_mission; invoke it so the
    # completion-context + sandbox-id-on-brief side effects are exercised.
    def _launch(bundle_arg, *, user, run_id, on_sandbox_created):
        on_sandbox_created("sb-1")
        return "sb-1"

    with (
        patch("products.pulse.backend.temporal.activities.launch_mission", side_effect=_launch),
        patch("products.pulse.backend.temporal.activities.store_completion_context") as store_mock,
    ):
        with pytest.raises(_CompleteAsyncError):
            await env.run(
                launch_agent_activity, LaunchAgentInputs(team_id=team.pk, brief_id=str(brief.id), bundle=bundle)
            )
    store_mock.assert_called_once()
    assert store_mock.call_args.args[1] == "sb-1"
    # Sandbox id pinned on the brief so a timed-out run can still be cleaned up.
    reloaded = await _reload_brief(brief.id)
    assert reloaded.agent_session_ref == "sb-1"


async def test_launch_agent_activity_refuses_without_creating_user(team, user) -> None:
    brief = await _create_brief(team, None)
    bundle = await _bundle_dict(team, brief)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(launch_agent_activity, LaunchAgentInputs(team_id=team.pk, brief_id=str(brief.id), bundle=bundle))
    assert exc_info.value.non_retryable is True


async def test_finalize_agent_activity_stores_session_ref_and_transcript_on_brief(team, user) -> None:
    brief = await _create_brief(team, user)
    bundle = await _bundle_dict(team, brief)
    env = ActivityEnvironment()
    run_result = MissionRunResult(report={"sections": []}, agent_session_ref="sb-1", transcript_key="pulse/t.log")
    with patch("products.pulse.backend.temporal.activities.finalize_mission", return_value=run_result) as fin_mock:
        result = await env.run(
            finalize_agent_activity,
            FinalizeAgentInputs(team_id=team.pk, brief_id=str(brief.id), bundle=bundle, sandbox_id="sb-1"),
        )
    assert result == dataclasses.asdict(run_result)
    assert fin_mock.call_args.args[0] == "sb-1"
    reloaded = await _reload_brief(brief.id)
    assert reloaded.agent_session_ref == "sb-1"
    assert "pulse/t.log" in reloaded.artifacts


async def test_finalize_agent_activity_does_not_retry_oversized_report(team, user) -> None:
    # An oversized report is deterministic, so retrying re-reads the same sandbox for nothing.
    brief = await _create_brief(team, user)
    bundle = await _bundle_dict(team, brief)
    env = ActivityEnvironment()
    with patch(
        "products.pulse.backend.temporal.activities.finalize_mission", side_effect=ReportTooLargeError("too big")
    ):
        with pytest.raises(ApplicationError) as exc_info:
            await env.run(
                finalize_agent_activity,
                FinalizeAgentInputs(team_id=team.pk, brief_id=str(brief.id), bundle=bundle, sandbox_id="sb-1"),
            )
    assert exc_info.value.non_retryable is True


async def test_cleanup_orphaned_sandbox_activity_tears_down(team) -> None:
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.cleanup_sandbox") as cleanup_mock:
        await env.run(cleanup_orphaned_sandbox_activity, CleanupSandboxInputs(sandbox_id="sb-1"))
    cleanup_mock.assert_called_once_with("sb-1")


async def test_synthesize_activity_marks_ready(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert status == ProductBrief.Status.READY
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.READY
    assert await _opportunity_count(team) == 1


async def test_synthesize_activity_persists_goal_status_from_config(team, user) -> None:
    # The activity's config-present branch must compute the goal status and thread it into
    # persistence; a qualitative goal (no metric) exercises the wiring without an insight read.
    brief = await _create_brief_with_goal(team, user, "Grow activation")
    env = ActivityEnvironment()
    item = {"source": "stub", "kind": "movement", "title": "t", "description": "d"}
    with patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()):
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[item]),
        )
    reloaded = await _reload_brief(brief.id)
    assert reloaded.goal_status is not None
    assert reloaded.goal_status["goal"] == "Grow activation"
    assert reloaded.goal_status["metric_state"] == "none"


async def test_synthesize_activity_without_creating_user_raises(team) -> None:
    # No creating user means no billing/quota attribution for the LLM call — fail non-retryably.
    brief = await _create_userless_brief(team)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert exc_info.value.non_retryable is True


def test_workflow_inputs_carry_slo_config() -> None:
    # The workflow input must be able to carry an SloConfig for the SloInterceptor to read at start;
    # a plain input (no SLO) stays valid too.
    slo = SloConfig(
        operation=SloOperation.PULSE_BRIEF_GENERATION,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=1,
        resource_id="brief-1",
        distinct_id="user-1",
    )
    inputs = GenerateBriefWorkflowInputs(team_id=1, brief_id="brief-1", slo=slo)
    assert inputs.slo is slo
    assert inputs.slo.operation == SloOperation.PULSE_BRIEF_GENERATION
    assert GenerateBriefWorkflowInputs(team_id=1, brief_id="brief-1").slo is None


def test_resolve_period_since_last_run_vs_last_n_days() -> None:
    now = dt.datetime(2026, 1, 20, tzinfo=dt.UTC)
    # last_n_days uses the requested day count regardless of prior runs.
    fixed = resolve_period({"type": "last_n_days", "days": 14}, now, last_run=dt.datetime(2026, 1, 18, tzinfo=dt.UTC))
    assert fixed.lookback_days == 14
    assert fixed.start_date == dt.date(2026, 1, 6)
    assert fixed.end_date == dt.date(2026, 1, 20)
    # since_last_run measures the gap to the last ready brief.
    since = resolve_period({"type": "since_last_run"}, now, last_run=dt.datetime(2026, 1, 15, tzinfo=dt.UTC))
    assert since.lookback_days == 5
    # since_last_run with no prior run falls back to the default window.
    first = resolve_period({"type": "since_last_run"}, now, last_run=None)
    assert first.lookback_days == 7


@pytest.mark.parametrize(
    "sources,expect_raise",
    [
        ([_RaisingSource(), _EmptySource()], False),  # partial failure in a quiet week -> empty brief, no raise
        ([_RaisingSource(), _RaisingSource()], True),  # every source failed -> retryable error
    ],
)
async def test_gather_activity_failed_sources(team, sources, expect_raise) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    inputs = GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None)
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=sources):
        if expect_raise:
            with pytest.raises(ApplicationError) as exc_info:
                await env.run(gather_brief_inputs_activity, inputs)
            assert exc_info.value.non_retryable is False
        else:
            assert await env.run(gather_brief_inputs_activity, inputs) == []


async def test_gather_activity_cap_orders_all_three_kinds(team) -> None:
    # health > movement > context: with all three over the cap, health and movement survive whole
    # and context is the only kind truncated — a priority swap between movement and context fails this.
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    sources = [_ManyItemsSource("context", 30), _ManyItemsSource("movement", 25), _ManyItemsSource("health", 10)]
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=sources):
        items = await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None),
        )
    assert len(items) == MAX_ITEMS
    kept = {kind: sum(1 for item in items if item["kind"] == kind) for kind in ("health", "movement", "context")}
    assert kept == {"health": 10, "movement": 25, "context": 15}


async def test_workflow_marks_brief_failed_when_gather_fails(team, user) -> None:
    await _set_ai_consent(team, False)  # gather refuses (non-retryable) — the failure path under test
    brief = await _create_brief(team, user)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[GenerateProductBriefWorkflow],
            activities=ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    GenerateProductBriefWorkflow.run,
                    GenerateBriefWorkflowInputs(team_id=team.pk, brief_id=str(brief.id)),
                    id=f"pulse-brief-test-{uuid.uuid4()}",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.FAILED
    assert "AI data processing not approved" in (reloaded.error or "")
