from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings
from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.temporal.agentic.scout_coordinator import (
    DEFAULT_ENROLLED_TEAM_IDS,
    SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID,
    CoordinatorWorkflowInput,
    CoordinatorWorkflowOutput,
    FetchEnabledRunsInput,
    PlannedRun,
    SignalsScoutCoordinatorWorkflow,
    StampDispatchedRunsInput,
    _enrolled_team_ids,
    _read_flag_payload,
    _team_configs,
    fetch_enabled_signals_scout_runs_activity,
    stamp_dispatched_signals_scout_runs_activity,
)
from products.skills.backend.models.skills import LLMSkill

_PAYLOAD_PATH = "products.signals.backend.temporal.agentic.scout_coordinator.posthoganalytics.get_feature_flag_payload"
_IS_CLOUD_PATH = "products.signals.backend.temporal.agentic.scout_coordinator.is_cloud"

# Enrollment is driven by the `signals-scout` flag payload allowlist. These async tests commit
# (no transaction rollback across the worker thread), so leftover teams from other modules can
# leak in. Enroll only the teams this module created to keep the scan deterministic.
_FLAGGED_TEAM_IDS: set[str] = set()


def _allowlist_payload() -> dict:
    return {"guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS]}


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
    """Enroll every team this module created via the `signals-scout` flag payload allowlist.

    Tests covering enrollment itself opt out with `@pytest.mark.flag_off` and set their own
    payload.
    """
    if request.node.get_closest_marker("flag_off"):
        yield
        return
    with patch(_PAYLOAD_PATH, side_effect=lambda *a, **k: _allowlist_payload()):
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


# ── Enrollment: the signals-scout flag payload allowlist is the single gate ──────


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"guaranteed_team_ids": [5, 6]}, {5, 6}),
        ({"guaranteed_team_ids": [5, 6], "skip_team_ids": [6]}, {5}),
        ('{"guaranteed_team_ids": [7]}', {7}),  # JSON string payload
        ({"guaranteed_team_ids": []}, set()),  # explicit empty list → intentional drain-all
        ({}, set(DEFAULT_ENROLLED_TEAM_IDS)),  # absent key → defaults
        (None, set(DEFAULT_ENROLLED_TEAM_IDS)),  # no payload → defaults
        ({"guaranteed_team_ids": "nope"}, set(DEFAULT_ENROLLED_TEAM_IDS)),  # wrong type → defaults
        ({"guaranteed_team_ids": [5, 6], "skip_team_ids": "nope"}, {5, 6}),  # bad skip ignored
    ],
)
@pytest.mark.flag_off
def test_enrolled_team_ids_parses_payload(payload, expected):
    # is_cloud → True so the fallback resolves to DEFAULT_ENROLLED_TEAM_IDS (see the
    # off-cloud fail-closed case below).
    with patch(_PAYLOAD_PATH, return_value=payload), patch(_IS_CLOUD_PATH, return_value=True):
        assert _enrolled_team_ids(_read_flag_payload()) == expected


@pytest.mark.flag_off
def test_enrolled_team_ids_uses_match_value_true():
    # The team list lives in the payload, not the release conditions — assert we request the
    # true-variant payload so a group-targeted/disabled flag can't starve discovery.
    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": [9]}) as mock_payload:
        _read_flag_payload()
    args, kwargs = mock_payload.call_args
    assert args[0] == "signals-scout"
    assert args[1] == SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID
    assert kwargs.get("match_value") is True


@pytest.mark.flag_off
def test_enrolled_team_ids_falls_back_to_defaults_on_error():
    with patch(_PAYLOAD_PATH, side_effect=RuntimeError("flag service down")), patch(_IS_CLOUD_PATH, return_value=True):
        assert _enrolled_team_ids(_read_flag_payload()) == set(DEFAULT_ENROLLED_TEAM_IDS)


@pytest.mark.flag_off
@override_settings(DEBUG=False)
def test_enrolled_team_ids_fails_closed_off_cloud():
    # Self-hosted (not cloud, not debug): a missing payload enrolls no one, so the coordinator
    # never starts scout runs for an unintended tenant. An explicit payload is still honored.
    with patch(_IS_CLOUD_PATH, return_value=False):
        with patch(_PAYLOAD_PATH, return_value=None):
            assert _enrolled_team_ids(_read_flag_payload()) == set()
        with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": [5]}):
            assert _enrolled_team_ids(_read_flag_payload()) == {5}


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_team_not_in_allowlist_is_skipped(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=True)

    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": []}):
        planned = await _run_activity()

    assert planned == []


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_skip_team_ids_drains_an_enrolled_team(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")

    # Enrolled via guaranteed but overridden by skip → drained.
    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": [ateam.id], "skip_team_ids": [ateam.id]}):
        planned = await _run_activity()

    assert all(p.team_id != ateam.id for p in planned)


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
    assert config.run_interval_minutes == 60
    assert config.emit is True
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
@pytest.mark.parametrize(
    "seconds_short,expected_skill_names",
    [
        (5, ["signals-scout-foo"]),  # within grace — stamp jitter shouldn't halve cadence
        (120, []),  # beyond grace — genuinely not due yet
    ],
)
async def test_due_check_grace_boundary(ateam, seconds_short, expected_skill_names):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")
    last_run = timezone.now() - timedelta(minutes=60) + timedelta(seconds=seconds_short)
    await database_sync_to_async(_create_config)(
        ateam, "signals-scout-foo", enabled=True, run_interval_minutes=60, last_run_at=last_run
    )

    planned = await _run_activity()

    assert [p.skill_name for p in planned] == expected_skill_names


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_overdue_config_is_planned_without_stamping(ateam):
    # Planning only selects due runs — it must NOT advance last_run_at. The schedule is
    # stamped after dispatch (see test_stamp_activity_advances_dispatched_configs) so a
    # fan-out failure can't suppress a scout for a full interval.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")
    old = timezone.now() - timedelta(minutes=2000)
    config = await database_sync_to_async(_create_config)(
        ateam, "signals-scout-foo", enabled=True, run_interval_minutes=1440, last_run_at=old
    )

    planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-foo"]
    refreshed = await database_sync_to_async(SignalScoutConfig.all_teams.get)(pk=config.pk)
    assert refreshed.last_run_at == old


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_stamp_activity_advances_dispatched_configs(ateam):
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-foo")
    old = timezone.now() - timedelta(minutes=2000)
    config = await database_sync_to_async(_create_config)(
        ateam, "signals-scout-foo", enabled=True, run_interval_minutes=1440, last_run_at=old
    )

    before = timezone.now()
    env = ActivityEnvironment()
    await env.run(
        stamp_dispatched_signals_scout_runs_activity,
        StampDispatchedRunsInput(dispatched_runs=[PlannedRun(team_id=ateam.id, skill_name="signals-scout-foo")]),
    )

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
async def test_per_team_tick_cap_defers_overflow(ateam):
    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    with patch("products.signals.backend.temporal.agentic.scout_coordinator.MAX_RUNS_PER_TEAM_PER_TICK", 2):
        planned = await _run_activity()

    assert sorted(p.skill_name for p in planned) == ["signals-scout-mid", "signals-scout-most"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_global_cap_is_split_fairly_across_teams(ateam, aother_team):
    # Team A has three due scouts, all more overdue than team B's two. With the global cap
    # at 3, pure most-overdue-first would hand A the whole tick; round-robin must give B a
    # slot in the first round.
    now = timezone.now()
    for name, hours in [("signals-scout-a1", 30), ("signals-scout-a2", 20), ("signals-scout-a3", 10)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _seed_other():
        with team_scope(aother_team.id, canonical=True):
            for name, hours in [("signals-scout-b1", 5), ("signals-scout-b2", 4)]:
                _create_skill(aother_team, name)
                _create_config(
                    aother_team, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
                )

    await database_sync_to_async(_seed_other)()

    with patch("products.signals.backend.temporal.agentic.scout_coordinator.MAX_RUNS_PER_TICK", 3):
        planned = await _run_activity()

    assert sorted((p.team_id, p.skill_name) for p in planned) == [
        (ateam.id, "signals-scout-a1"),
        (ateam.id, "signals-scout-a2"),
        (aother_team.id, "signals-scout-b1"),
    ]


# ── Per-team config overrides via the flag payload (optional, opt-in per team) ───


@pytest.mark.parametrize(
    "payload,expected",
    [
        # String keys (JSON object keys) coerced to int; arbitrary config blob kept verbatim.
        (
            {"team_configs": {"5": {"max_runs_per_tick": 10}, "6": {"max_runs_per_tick": 3}}},
            {5: {"max_runs_per_tick": 10}, 6: {"max_runs_per_tick": 3}},
        ),
        ('{"team_configs": {"9": {"max_runs_per_tick": 7}}}', {9: {"max_runs_per_tick": 7}}),  # JSON string payload
        ({"team_configs": {"5": "nope"}}, {}),  # non-dict config value dropped
        ({"team_configs": "nope"}, {}),  # wrong type → empty
        ({}, {}),  # absent key → existing behaviour (no overrides)
        (None, {}),  # no payload → no overrides
    ],
)
@pytest.mark.flag_off
def test_team_configs_parses_payload(payload, expected):
    with patch(_PAYLOAD_PATH, return_value=payload):
        assert _team_configs(_read_flag_payload()) == expected


@pytest.mark.flag_off
def test_team_configs_falls_back_to_empty_on_error():
    # A read error never breaks dispatch — every team falls back to the global default cap.
    with patch(_PAYLOAD_PATH, side_effect=RuntimeError("flag service down")):
        assert _team_configs(_read_flag_payload()) == {}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_per_team_config_cap_override_takes_precedence(ateam):
    # Three due scouts. A `team_configs` override caps THIS team at 1/tick (below the global
    # default of 50), so only its single most-overdue scout dispatches — proving the per-team
    # override is read from the flag payload and takes precedence.
    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "team_configs": {str(ateam.id): {"max_runs_per_tick": 1}},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-most"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_team_without_config_override_keeps_global_default(ateam):
    # An override set for a DIFFERENT team must not affect this one — it keeps the global
    # default. Both this team's due scouts dispatch (global default of 50 is not exceeded).
    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "team_configs": {"999999": {"max_runs_per_tick": 1}},  # some other team
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    assert sorted(p.skill_name for p in planned) == ["signals-scout-mid", "signals-scout-most"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_per_team_config_override_keyed_by_child_env_applies_to_parent(ateam, aorganization):
    # An operator enrolls a child environment id (the same id they'd list in guaranteed_team_ids).
    # Planning canonicalizes that child to its parent project, so a team_configs override keyed by
    # the child id must be canonicalized the same way to land on the parent. Cap at 1/tick via the
    # child-keyed override and assert only the most-overdue scout dispatches.
    child = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCoordinatorChildEnv-{random.randint(1, 99999)}",
        parent_team=ateam,
    )

    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [child.id],
            "team_configs": {str(child.id): {"max_runs_per_tick": 1}},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-most"]

    await sync_to_async(child.delete)()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_auto_register_past_enabled_cap_creates_disabled_config(ateam):
    # One enabled scout puts the team at the (patched) cap; a freshly authored skill must
    # still get a config row — but disabled, so it adds no spend and isn't planned.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-existing")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-existing", enabled=True)
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-fresh")

    with patch("products.signals.backend.scout_harness.config_registry.MAX_ENABLED_SCOUTS_PER_TEAM", 1):
        planned = await _run_activity()

    fresh = await database_sync_to_async(
        lambda: SignalScoutConfig.all_teams.get(team_id=ateam.id, skill_name="signals-scout-fresh")
    )()
    assert fresh.enabled is False
    assert sorted(p.skill_name for p in planned) == ["signals-scout-existing"]


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


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.real_canonical_sync
async def test_payload_enrolled_unseeded_team_is_seeded_by_tick(ateam):
    # The flag-driven path with no manual seed: ateam is enrolled via the payload (autouse
    # fixture) but has no scout skills yet. The tick itself must seed the canonical fleet,
    # register configs, and dispatch — proving an operator only edits the flag payload.
    pre_seeded = await database_sync_to_async(
        lambda: LLMSkill.objects.filter(team=ateam, name__startswith="signals-scout-").exists()
    )()
    assert pre_seeded is False

    planned = await _run_activity()

    config_names = await database_sync_to_async(
        lambda: set(SignalScoutConfig.all_teams.filter(team=ateam).values_list("skill_name", flat=True))
    )()
    assert config_names  # fleet seeded + configs auto-registered by the tick
    assert {p.skill_name for p in planned} == config_names


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


@pytest.mark.asyncio
async def test_hard_dispatch_error_does_not_stamp():
    # A non-dedupe start_child error must abort before the stamp activity, so the affected
    # configs stay unstamped and re-dispatch next tick instead of being suppressed.
    planned = [PlannedRun(team_id=1, skill_name="signals-scout-a")]
    fake_fetch_result = type("R", (), {"planned_runs": planned})()
    execute_activity_calls: list[Any] = []

    async def fake_execute_activity(activity, *args, **kwargs):
        execute_activity_calls.append(activity)
        return fake_fetch_result

    async def fake_start_child(_workflow_run, run_input, **kwargs):
        raise RuntimeError("temporal unavailable")

    coordinator = SignalsScoutCoordinatorWorkflow()
    with (
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.execute_activity",
            side_effect=fake_execute_activity,
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.info",
            return_value=type("Info", (), {"workflow_id": "tick-1"})(),
        ),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator.workflow.start_child_workflow",
            side_effect=fake_start_child,
        ),
    ):
        with pytest.raises(RuntimeError, match="temporal unavailable"):
            await coordinator.run(CoordinatorWorkflowInput())

    # Only the planning activity ran — the stamp activity never executed.
    assert execute_activity_calls == [fetch_enabled_signals_scout_runs_activity]
