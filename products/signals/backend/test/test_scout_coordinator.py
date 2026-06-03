from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.temporal.agentic.scout_coordinator import (
    CoordinatorWorkflowInput,
    CoordinatorWorkflowOutput,
    FetchEnabledRunsInput,
    PlannedRun,
    SignalsScoutCoordinatorWorkflow,
    fetch_enabled_signals_scout_runs_activity,
)

_FLAG_PATH = "products.signals.backend.temporal.agentic.scout_coordinator.posthoganalytics.feature_enabled"

# The coordinator scans every team in the DB. These async tests commit (no transaction
# rollback across the worker thread), so leftover teams from other modules can leak into
# the scan. Flag only the teams this module created to keep the scan deterministic.
_FLAGGED_TEAM_IDS: set[str] = set()


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
    # Scout models use TeamScopedRootMixin (fail-closed); yield inside team_scope
    # so test bodies that touch `Model.objects.X()` find a context.
    # `canonical=True` skips the sync DB resolution lookup (illegal from async).
    _FLAGGED_TEAM_IDS.add(str(team.id))
    with team_scope(team.id, canonical=True):
        yield team
    _FLAGGED_TEAM_IDS.discard(str(team.id))
    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def aother_team(aorganization):
    # Sibling team for cross-team tests; not entered into team_scope (only one scope
    # can be active at a time). Cross-team writes use team_scope(...) explicitly.
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCoordinatorOtherTeam-{random.randint(1, 99999)}",
    )
    _FLAGGED_TEAM_IDS.add(str(team.id))
    yield team
    _FLAGGED_TEAM_IDS.discard(str(team.id))
    await sync_to_async(team.delete)()


def _create_skill(team: Team, name: str) -> LLMSkill:
    return LLMSkill.objects.create(team=team, name=name, description="d", body="b")


def _create_config(team: Team, skill_name: str, **kwargs: Any) -> SignalScoutConfig:
    return SignalScoutConfig.objects.create(team=team, skill_name=skill_name, **kwargs)


@pytest.fixture(autouse=True)
def _flag_on(request):
    """Treat every team as in the dogfood flag by default.

    Tests covering the gate itself opt out with `@pytest.mark.flag_off` and set their own
    `feature_enabled` behavior.
    """
    if request.node.get_closest_marker("flag_off"):
        yield
        return
    with patch(_FLAG_PATH, side_effect=lambda key, distinct_id, *a, **k: distinct_id in _FLAGGED_TEAM_IDS):
        yield


@pytest.fixture(autouse=True)
def _stub_canonical_sync(request):
    """Stub `sync_canonical_skills` to a no-op so tests assert on hand-authored skills only.

    Tests that exercise the real sync opt out via `@pytest.mark.real_canonical_sync`.
    """
    if request.node.get_closest_marker("real_canonical_sync"):
        yield
        return
    with patch(
        "products.signals.backend.temporal.agentic.scout_coordinator.sync_canonical_skills",
        return_value=None,
    ):
        yield


async def _run_activity() -> list[PlannedRun]:
    env = ActivityEnvironment()
    output = await env.run(fetch_enabled_signals_scout_runs_activity, FetchEnabledRunsInput())
    return output.planned_runs


# ── Gate: the signals-scout flag is the single team-level gate ───────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_team_not_in_flag_is_skipped(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=True)

    with patch(_FLAG_PATH, return_value=False):
        planned = await _run_activity()

    assert planned == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_disabled_config_is_skipped(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=False)

    assert await _run_activity() == []


# ── Auto-register: author a skill, get a scout ──────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_authoring_skill_auto_registers_enabled_config_and_runs(ateam):
    # No config yet — just the authored skill.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")

    planned = await _run_activity()

    config = await database_sync_to_async(SignalScoutConfig.all_teams.get)(team=ateam, skill_name="signals-scout-foo")
    assert config.enabled is True
    assert config.run_interval_minutes == 1440
    assert config.emit is False
    # Never-run row is immediately due, so it's dispatched this tick.
    assert [(p.team_id, p.skill_name) for p in planned] == [(ateam.id, "signals-scout-foo")]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_non_scout_skills_are_ignored(ateam):
    await database_sync_to_async(_create_skill)(ateam, "custom-helper")

    assert await _run_activity() == []
    count = await database_sync_to_async(SignalScoutConfig.all_teams.filter(team=ateam).count)()
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_config_whose_skill_is_gone_is_skipped(ateam):
    # A config whose `signals-scout-*` skill was deleted (or is no longer latest) must not be
    # dispatched — its child workflow would only fail in load_skill_for_run every tick.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-live")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-live", enabled=True)
    await database_sync_to_async(_create_config)(ateam, "signals-scout-ghost", enabled=True)

    planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-live"]


# ── Schedule: deterministic due-check, no sampling ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_config_within_interval_is_not_due(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")
    await database_sync_to_async(_create_config)(
        ateam, "signals-scout-foo", enabled=True, run_interval_minutes=1440, last_run_at=timezone.now()
    )

    assert await _run_activity() == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_overdue_config_runs_and_stamps_last_run_at(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")
    old = timezone.now() - timedelta(minutes=2000)
    config = await database_sync_to_async(_create_config)(
        ateam, "signals-scout-foo", enabled=True, run_interval_minutes=1440, last_run_at=old
    )

    before = timezone.now()
    planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-foo"]
    refreshed = await database_sync_to_async(SignalScoutConfig.all_teams.get)(pk=config.pk)
    assert refreshed.last_run_at is not None and refreshed.last_run_at >= before


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_all_due_skills_run_no_sampling(ateam):
    # Every due scout runs — there's no per-tick sampling anymore.
    names = ["signals-scout-alpha", "signals-scout-beta", "signals-scout-gamma"]
    for name in names:
        await database_sync_to_async(_create_skill)(ateam, name)

    planned = await _run_activity()

    assert sorted(p.skill_name for p in planned) == names


# ── Cost bound: most-overdue first under the cap ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_cap_dispatches_most_overdue_first(ateam):
    now = timezone.now()
    # Three due scouts, descending overdue-ness; cap to 2 → the two most overdue win.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-most")
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-mid")
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-least")
    await database_sync_to_async(_create_config)(
        ateam, "signals-scout-most", enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=10)
    )
    await database_sync_to_async(_create_config)(
        ateam, "signals-scout-mid", enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=5)
    )
    await database_sync_to_async(_create_config)(
        ateam, "signals-scout-least", enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=2)
    )

    with patch("products.signals.backend.temporal.agentic.scout_coordinator.MAX_RUNS_PER_TICK", 2):
        planned = await _run_activity()

    assert sorted(p.skill_name for p in planned) == ["signals-scout-mid", "signals-scout-most"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_planned_runs_sorted_by_team_then_skill(ateam, aother_team):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-zeta")
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-alpha")

    def _seed_other():
        with team_scope(aother_team.id, canonical=True):
            _create_skill(aother_team, "signals-scout-errors")

    await database_sync_to_async(_seed_other)()

    planned = await _run_activity()

    keys = [(p.team_id, p.skill_name) for p in planned]
    assert keys == sorted(keys)
    assert set(keys) == {
        (ateam.id, "signals-scout-alpha"),
        (ateam.id, "signals-scout-zeta"),
        (aother_team.id, "signals-scout-errors"),
    }


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_seed_failure_does_not_abort_tick(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-existing")

    with patch(
        "products.signals.backend.temporal.agentic.scout_coordinator.sync_canonical_skills",
        side_effect=RuntimeError("simulated seed failure"),
    ):
        planned = await _run_activity()

    assert any(p.team_id == ateam.id and p.skill_name == "signals-scout-existing" for p in planned)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.real_canonical_sync
async def test_enrolled_team_registers_and_runs_canonical_fleet(ateam):
    # Enrolling a team seeds the canonical fleet; the coordinator then auto-registers a
    # config per seeded skill and dispatches the due ones.
    await database_sync_to_async(sync_canonical_skills)(ateam)
    seeded = await database_sync_to_async(
        lambda: set(
            LLMSkill.objects.filter(team=ateam, name__startswith="signals-scout-").values_list("name", flat=True)
        )
    )()
    assert seeded

    planned = await _run_activity()

    config_names = await database_sync_to_async(
        lambda: set(SignalScoutConfig.all_teams.filter(team=ateam).values_list("skill_name", flat=True))
    )()
    assert config_names == seeded
    assert {p.skill_name for p in planned} == seeded


# ── Workflow-level dispatch ─────────────────────────────────────────────────────
#
# The coordinator dispatches children fire-and-forget via `start_child_workflow` with
# `ParentClosePolicy.ABANDON`. We patch the activity + `start_child_workflow` and assert
# dispatch counts (started vs already-running skip), not completion outcomes.


@pytest.mark.asyncio
async def test_workflow_returns_zero_counts_when_no_planned_runs():
    coordinator = SignalsScoutCoordinatorWorkflow()
    fake_fetch_result = type("R", (), {"planned_runs": []})()

    with patch(
        "products.signals.backend.temporal.agentic.scout_coordinator.workflow.execute_activity",
        new_callable=AsyncMock,
        return_value=fake_fetch_result,
    ):
        output = await coordinator.run(CoordinatorWorkflowInput())

    assert output == CoordinatorWorkflowOutput(0, 0, 0)


@pytest.mark.asyncio
async def test_workflow_dispatches_children_fire_and_forget():
    planned = [
        PlannedRun(team_id=1, skill_name="signals-scout-a"),
        PlannedRun(team_id=1, skill_name="signals-scout-b"),
        PlannedRun(team_id=2, skill_name="signals-scout-c"),
    ]
    fake_fetch_result = type("R", (), {"planned_runs": planned})()

    # Second dispatch raises WorkflowAlreadyStartedError → counted as skipped, others as started.
    dispatch_outcomes: list[BaseException | None] = [
        None,
        WorkflowAlreadyStartedError("dup", "signals-scout-run-1-signals-scout-b-tick-1-1"),
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

    coordinator = SignalsScoutCoordinatorWorkflow()
    with (
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.execute_activity",
            new_callable=AsyncMock,
            return_value=fake_fetch_result,
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.info",
            return_value=type("Info", (), {"workflow_id": "tick-1"})(),
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.logger",
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.start_child_workflow",
            side_effect=fake_start_child,
        ),
    ):
        output = await coordinator.run(CoordinatorWorkflowInput())

    assert output.planned_count == 3
    assert output.started_count == 2
    assert output.skipped_count == 1
    assert dispatch_calls == [
        (1, "signals-scout-a"),
        (1, "signals-scout-b"),
        (2, "signals-scout-c"),
    ]
