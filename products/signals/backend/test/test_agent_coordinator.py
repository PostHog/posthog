from __future__ import annotations

import random

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalAgentConfig
from products.signals.backend.temporal.agentic.agent_coordinator import (
    MAX_RUNS_PER_TICK,
    CoordinatorWorkflowInput,
    CoordinatorWorkflowOutput,
    FetchEnabledRunsInput,
    PlannedRun,
    SignalsAgentCoordinatorWorkflow,
    fetch_enabled_signals_agent_runs_activity,
)


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsCoordinatorTestOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCoordinatorTestTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def aother_team(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCoordinatorOtherTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


def _create_skill(team: Team, name: str) -> LLMSkill:
    return LLMSkill.objects.create(team=team, name=name, description="d", body="b")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_disabled_config_is_skipped(ateam):
    # enabled defaults to False — get_or_create gives a disabled row.
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=False)
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-errors")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert output.planned_runs == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_null_skill_list_globs_signals_agent_prefix(ateam):
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True, enabled_skill_names=None)
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-errors")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-llm")
    # Non-matching prefix is ignored.
    await database_sync_to_async(_create_skill)(ateam, "custom-helper")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    names = [p.skill_name for p in output.planned_runs]
    assert names == ["signals-agent-errors", "signals-agent-llm"]
    assert all(p.team_id == ateam.id for p in output.planned_runs)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_explicit_skill_list_filters_to_existing_only(ateam):
    await database_sync_to_async(SignalAgentConfig.objects.create)(
        team=ateam,
        enabled=True,
        enabled_skill_names=["signals-agent-errors", "signals-agent-typo"],
    )
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-errors")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-llm")  # not in list

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert [p.skill_name for p in output.planned_runs] == ["signals-agent-errors"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_budget_overrides_propagate_to_planned_run(ateam):
    await database_sync_to_async(SignalAgentConfig.objects.create)(
        team=ateam,
        enabled=True,
        budget_overrides={"max_runtime_s": 900},
    )
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-errors")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert len(output.planned_runs) == 1
    assert output.planned_runs[0].budget_overrides == {"max_runtime_s": 900}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_planned_runs_sort_by_team_then_skill(ateam, aother_team):
    # Insert in the "wrong" order to verify sort behavior.
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=aother_team, enabled=True)
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True)
    await database_sync_to_async(_create_skill)(aother_team, "signals-agent-errors")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-zeta")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-alpha")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    pairs = [(p.team_id, p.skill_name) for p in output.planned_runs]
    # Sort key: (team_id, skill_name) — primary by team, secondary by skill name.
    assert pairs == sorted(pairs)
    assert set(pairs) == {
        (ateam.id, "signals-agent-alpha"),
        (ateam.id, "signals-agent-zeta"),
        (aother_team.id, "signals-agent-errors"),
    }


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_lazy_seeds_canonical_skills_for_brand_new_team(ateam):
    # An enabled config on a brand-new team (no signals-agent-* skills yet) should
    # still produce planned runs: the coordinator lazy-seeds the canonical set on
    # first encounter so the cadence path doesn't depend on a manual seed step.
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True, enabled_skill_names=None)

    pre = await database_sync_to_async(
        lambda: list(
            LLMSkill.objects.filter(team=ateam, name__startswith="signals-agent-").values_list("name", flat=True)
        )
    )()
    assert pre == []

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    seeded = await database_sync_to_async(
        lambda: list(
            LLMSkill.objects.filter(team=ateam, name__startswith="signals-agent-").values_list("name", flat=True)
        )
    )()
    # The canonical fleet ships `signals-agent-general` (cross-product generalist) plus
    # specialists; assert at least one canonical skill was seeded and made it into
    # planned runs, rather than naming a specific one (so future canonical additions
    # or renames don't break this test).
    assert any(name.startswith("signals-agent-") for name in seeded)
    assert any(p.skill_name.startswith("signals-agent-") for p in output.planned_runs)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_lazy_seed_failure_does_not_abort_tick(ateam, aother_team):
    # If lazy seed fails for one team, the coordinator should still plan runs for
    # other teams and for skills that already exist on the failing team.
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True)
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=aother_team, enabled=True)
    # ateam already has a hand-authored skill — the seed call shouldn't even fire
    # for them (existing-rows short-circuit) but if it did and somehow raised,
    # we still want planning to succeed.
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-existing")

    with patch(
        "products.signals.backend.temporal.agentic.agent_coordinator.seed_canonical_skills",
        side_effect=RuntimeError("simulated seed failure"),
    ):
        env = ActivityEnvironment()
        output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    # ateam's existing skill is still plannable; aother_team has no skills and
    # the failed seed left it empty, so it contributes nothing — but the tick
    # didn't crash.
    assert any(p.team_id == ateam.id and p.skill_name == "signals-agent-existing" for p in output.planned_runs)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_truncates_above_hard_cap(ateam):
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True)
    # Exceed the cap.
    for i in range(MAX_RUNS_PER_TICK + 5):
        await database_sync_to_async(_create_skill)(ateam, f"signals-agent-{i:03d}")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert len(output.planned_runs) == MAX_RUNS_PER_TICK


# ── Workflow-level tests ────────────────────────────────────────────────────────
#
# The coordinator dispatches child workflows fire-and-forget via `start_child_workflow`
# with `ParentClosePolicy.ABANDON`, so it returns as soon as the last dispatch resolves.
# We patch the activity + `start_child_workflow` and assert dispatch counts (started vs
# already-running skip) rather than completion outcomes — child runtime success is the
# child workflow's contract, not the coordinator's.


@pytest.mark.asyncio
async def test_workflow_returns_zero_counts_when_no_planned_runs():
    coordinator = SignalsAgentCoordinatorWorkflow()
    fake_fetch_result = type("R", (), {"planned_runs": []})()

    with patch(
        "products.signals.backend.temporal.agentic.agent_coordinator.workflow.execute_activity",
        new_callable=AsyncMock,
        return_value=fake_fetch_result,
    ):
        output = await coordinator.run(CoordinatorWorkflowInput())

    assert output == CoordinatorWorkflowOutput(0, 0, 0)


@pytest.mark.asyncio
async def test_workflow_dispatches_children_fire_and_forget():
    planned = [
        PlannedRun(team_id=1, skill_name="signals-agent-a"),
        PlannedRun(team_id=1, skill_name="signals-agent-b"),
        PlannedRun(team_id=2, skill_name="signals-agent-c"),
    ]
    fake_fetch_result = type("R", (), {"planned_runs": planned})()

    # Second dispatch raises WorkflowAlreadyStartedError → counted as skipped, others as started.
    dispatch_outcomes: list[BaseException | None] = [
        None,
        WorkflowAlreadyStartedError("dup", "signals-agent-run-1-signals-agent-b-tick-1-1"),
        None,
    ]
    dispatch_calls: list[tuple[int, str]] = []

    async def fake_start_child(_workflow_run, run_input, **kwargs):
        idx = len(dispatch_calls)
        dispatch_calls.append((run_input.team_id, run_input.skill_name))
        outcome = dispatch_outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        return AsyncMock()

    coordinator = SignalsAgentCoordinatorWorkflow()
    with (
        patch(
            "products.signals.backend.temporal.agentic.agent_coordinator.workflow.execute_activity",
            new_callable=AsyncMock,
            return_value=fake_fetch_result,
        ),
        patch(
            "products.signals.backend.temporal.agentic.agent_coordinator.workflow.info",
            return_value=type("Info", (), {"workflow_id": "tick-1"})(),
        ),
        patch(
            "products.signals.backend.temporal.agentic.agent_coordinator.workflow.logger",
        ),
        patch(
            "products.signals.backend.temporal.agentic.agent_coordinator.workflow.start_child_workflow",
            side_effect=fake_start_child,
        ),
    ):
        output = await coordinator.run(CoordinatorWorkflowInput())

    assert output.planned_count == 3
    assert output.started_count == 2
    assert output.skipped_count == 1
    # All three planned runs were dispatched in order, even though one was a dedupe-skip.
    assert dispatch_calls == [
        (1, "signals-agent-a"),
        (1, "signals-agent-b"),
        (2, "signals-agent-c"),
    ]
