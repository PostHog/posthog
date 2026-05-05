from __future__ import annotations

import random
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalAgentConfig
from products.signals.backend.temporal.agentic.agent_coordinator import (
    DEFAULT_STAGGER_MINUTES,
    CoordinatorWorkflowInput,
    CoordinatorWorkflowOutput,
    FetchEnabledRunsInput,
    PlannedRun,
    SignalsAgentCoordinatorWorkflow,
    fetch_enabled_signals_agent_runs_activity,
)
from products.signals.backend.temporal.agentic.agent_scheduler import RunSignalsAgentOutput


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
async def test_null_skill_list_globs_signals_agent_prefix_then_samples_one(ateam):
    """`enabled_skill_names=None` widens the candidate pool to all `signals-agent-*`
    skills on the team; the coordinator then samples one uniformly per tick."""
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True, enabled_skill_names=None)
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-errors")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-llm")
    # Non-matching prefix is ignored.
    await database_sync_to_async(_create_skill)(ateam, "custom-helper")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    # Exactly one planned run, drawn from the two matching candidates.
    assert len(output.planned_runs) == 1
    assert output.planned_runs[0].skill_name in {"signals-agent-errors", "signals-agent-llm"}
    assert output.planned_runs[0].team_id == ateam.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_explicit_skill_list_filters_to_existing_only(ateam):
    """`enabled_skill_names = [...]` narrows the candidate pool to that intersection
    with what's on the team. With one valid candidate, sampling returns it deterministically."""
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
async def test_sampling_picks_one_uniformly_from_candidates(ateam):
    """With multiple candidates on a single team, the coordinator picks exactly one
    via `random.choice`. Patching the choice gives us deterministic assertions."""
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True, enabled_skill_names=None)
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-alpha")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-beta")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-gamma")

    with patch(
        "products.signals.backend.temporal.agentic.agent_coordinator.random.choice",
        side_effect=lambda candidates: candidates[1],  # always pick the middle
    ):
        env = ActivityEnvironment()
        output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    # Candidates are sorted before sampling, so index 1 == "signals-agent-beta".
    assert [p.skill_name for p in output.planned_runs] == ["signals-agent-beta"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_sampling_pool_respects_enabled_skill_names_constraint(ateam):
    """When `enabled_skill_names` is set, the sampling pool is the intersection of
    that list with skills actually present on the team — not the full glob."""
    await database_sync_to_async(SignalAgentConfig.objects.create)(
        team=ateam,
        enabled=True,
        enabled_skill_names=["signals-agent-alpha", "signals-agent-beta"],
    )
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-alpha")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-beta")
    # Off-list skill exists on the team but is excluded from sampling.
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-gamma")

    captured: dict[str, Any] = {}

    def _capture_and_choose(candidates):
        captured["candidates"] = list(candidates)
        return candidates[0]

    with patch(
        "products.signals.backend.temporal.agentic.agent_coordinator.random.choice",
        side_effect=_capture_and_choose,
    ):
        env = ActivityEnvironment()
        output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert captured["candidates"] == ["signals-agent-alpha", "signals-agent-beta"]
    assert "signals-agent-gamma" not in captured["candidates"]
    assert [p.skill_name for p in output.planned_runs] == ["signals-agent-alpha"]


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
async def test_planned_runs_one_per_team_sorted_by_team_id(ateam, aother_team):
    """One PlannedRun per enabled team (sampling-of-one), sorted by team_id so the
    stagger assignment is stable across ticks."""
    # Insert in the "wrong" order to verify sort behavior.
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=aother_team, enabled=True)
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True)
    await database_sync_to_async(_create_skill)(aother_team, "signals-agent-errors")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-zeta")
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-alpha")

    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    # One PlannedRun per team; ateam's run is one of {alpha, zeta} via sampling.
    assert len(output.planned_runs) == 2
    team_ids = [p.team_id for p in output.planned_runs]
    assert team_ids == sorted(team_ids)
    by_team = {p.team_id: p.skill_name for p in output.planned_runs}
    assert by_team[ateam.id] in {"signals-agent-alpha", "signals-agent-zeta"}
    assert by_team[aother_team.id] == "signals-agent-errors"


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
    # signals-agent-general is the canonical baseline skill shipped in-repo; assert
    # membership rather than equality so future canonical additions don't break this test.
    assert "signals-agent-general" in seeded
    # Sampling-of-one means exactly one PlannedRun per team, drawn at random from the
    # seeded set. Assert the planned run names a real seeded skill rather than asserting
    # which one — the random pick is deliberate behavior.
    assert len(output.planned_runs) == 1
    assert output.planned_runs[0].skill_name in seeded


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
async def test_truncates_above_hard_cap(ateam, aother_team):
    """The hard cap defends against a config explosion across many teams. Sampling-of-one
    means the cap is now effectively per-team rather than per-skill, so we test it by
    enabling more teams than the (lowered) cap and verifying truncation kicks in."""
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam, enabled=True)
    await database_sync_to_async(SignalAgentConfig.objects.create)(team=aother_team, enabled=True)
    await database_sync_to_async(_create_skill)(ateam, "signals-agent-alpha")
    await database_sync_to_async(_create_skill)(aother_team, "signals-agent-beta")

    with patch("products.signals.backend.temporal.agentic.agent_coordinator.MAX_RUNS_PER_TICK", 1):
        env = ActivityEnvironment()
        output = await env.run(fetch_enabled_signals_agent_runs_activity, FetchEnabledRunsInput())

    assert len(output.planned_runs) == 1


# ── Workflow-level tests ────────────────────────────────────────────────────────
#
# We test the workflow's fan-out logic by patching the activity + child workflow
# launcher and driving `SignalsAgentCoordinatorWorkflow.run` directly. The full
# `WorkflowEnvironment` round-trip is more elaborate than necessary for the
# orchestration logic — the parts that matter (skip, fail, success aggregation,
# stagger sleep) are pure async control flow.


@pytest.mark.asyncio
async def test_workflow_returns_zero_counts_when_no_planned_runs():
    coordinator = SignalsAgentCoordinatorWorkflow()
    fake_fetch_result = type("R", (), {"planned_runs": []})()

    with patch(
        "products.signals.backend.temporal.agentic.agent_coordinator.workflow.execute_activity",
        new_callable=AsyncMock,
        return_value=fake_fetch_result,
    ):
        output = await coordinator.run(CoordinatorWorkflowInput(stagger_minutes=DEFAULT_STAGGER_MINUTES))

    assert output == CoordinatorWorkflowOutput(0, 0, 0, 0)


@pytest.mark.asyncio
async def test_workflow_aggregates_triggered_skipped_failed():
    planned = [
        PlannedRun(team_id=1, skill_name="signals-agent-a"),
        PlannedRun(team_id=1, skill_name="signals-agent-b"),
        PlannedRun(team_id=2, skill_name="signals-agent-c"),
    ]
    fake_fetch_result = type("R", (), {"planned_runs": planned})()

    outcomes: list[Any] = [
        RunSignalsAgentOutput(
            run_id="abc",
            status="completed",
            runtime_s=1.0,
            skill_name="signals-agent-a",
            skill_version=1,
        ),
        RunSignalsAgentOutput(
            run_id=None,
            status=None,
            runtime_s=0.0,
            skill_name="signals-agent-b",
            skill_version=1,
            skip_reason="prior run still in RUNNING status",
        ),
        RuntimeError("sandbox refused to start"),
    ]

    async def fake_launch(*, idx: int, **_kwargs: Any) -> RunSignalsAgentOutput:
        outcome = outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

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
            "products.signals.backend.temporal.agentic.agent_coordinator._launch_child_with_stagger",
            side_effect=fake_launch,
        ),
    ):
        output = await coordinator.run(CoordinatorWorkflowInput(stagger_minutes=0))

    assert output.planned_count == 3
    assert output.triggered_count == 1
    assert output.skipped_count == 1
    assert output.failed_count == 1
