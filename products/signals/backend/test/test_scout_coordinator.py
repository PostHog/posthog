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
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, sync_canonical_skills

# The flag-payload read + per-team cap resolution live in `scout_harness/team_limits.py`; helpers
# defined there are imported and patched there (see `_PAYLOAD_PATH` / `_IS_CLOUD_PATH`).
from products.signals.backend.scout_harness.team_limits import (
    DEFAULT_ENROLLED_TEAM_IDS,
    SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID,
    Enrollment,
    _default_team_config,
    _enrolled_team_ids,
    _parse_enrollment,
    _read_flag_payload,
    _resolve_enrolled,
    _resolve_global_max_runs_per_tick,
    _resolve_max_runs_per_day,
    _resolve_withheld_skills,
    _team_configs,
)
from products.signals.backend.temporal.agentic.scout_coordinator import (
    MAX_RUNS_PER_TICK,
    CoordinatorWorkflowInput,
    CoordinatorWorkflowOutput,
    FetchEnabledRunsInput,
    PlannedRun,
    SignalsScoutCoordinatorWorkflow,
    StampDispatchedRunsInput,
    _allocate_tick_budget,
    _DueRun,
    fetch_enabled_signals_scout_runs_activity,
    stamp_dispatched_signals_scout_runs_activity,
)
from products.skills.backend.models.skills import LLMSkill

_PAYLOAD_PATH = "products.signals.backend.scout_harness.team_limits.posthoganalytics.get_feature_flag_payload"
_IS_CLOUD_PATH = "products.signals.backend.scout_harness.team_limits.is_cloud"

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


def _create_skill(team: Team, name: str, *, seeded: bool = True) -> LLMSkill:
    # Default to a canonical (harness-seeded) skill — the realistic case; pass seeded=False for a
    # hand-authored custom scout (no `seeded_by` tag), which the seed allowlist must not gate.
    metadata = {"seeded_by": HARNESS_SEEDED_BY} if seeded else {}
    return LLMSkill.objects.create(team=team, name=name, description="d", body="b", metadata=metadata)


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


# ── Wildcard enrollment: "*" enrolls every team that has enabled scout configs ──────


@pytest.mark.parametrize(
    "guaranteed,skip,expected_wildcard,expected_explicit",
    [
        (["*"], None, True, set()),  # pure wildcard, no explicit ids
        (["*", 5], None, True, {5}),  # wildcard + a force-provisioned id
        ([5, 6], None, False, {5, 6}),  # no wildcard → today's allowlist behaviour
        (["*"], [5], True, set()),  # wildcard with a skip override
        ([], None, False, set()),  # empty list → intentional drain-all, NOT the fallback (cf. None)
        (["*", "nope"], None, False, set(DEFAULT_ENROLLED_TEAM_IDS)),  # bad entry → whole list malformed → fallback
    ],
)
@pytest.mark.flag_off
def test_parse_enrollment_wildcard(guaranteed, skip, expected_wildcard, expected_explicit):
    payload: dict[str, Any] = {"guaranteed_team_ids": guaranteed}
    if skip is not None:
        payload["skip_team_ids"] = skip
    with patch(_PAYLOAD_PATH, return_value=payload), patch(_IS_CLOUD_PATH, return_value=True):
        enrollment = _parse_enrollment(_read_flag_payload())
    assert enrollment.wildcard is expected_wildcard
    assert enrollment.explicit == expected_explicit
    assert enrollment.skip == (set(skip) if skip else set())


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_wildcard_dispatches_team_with_enabled_config(ateam):
    # A team NOT in any explicit allowlist still runs under "*" purely because it has an enabled
    # scout config (the self-serve gate). Membership assertion: the global wildcard scan can also
    # pick up configs leaked by other committing async tests, so we assert ateam is present, not
    # that it is the only one.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=True)

    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": ["*"]}):
        planned = await _run_activity()

    assert any(p.team_id == ateam.id and p.skill_name == "signals-scout-errors" for p in planned)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_wildcard_does_not_auto_seed_a_config_less_team(ateam):
    # Under "*" a team participates only if it ALREADY has configs — the wildcard never seeds from
    # nothing (that's the explicit-id path). A team with a scout skill but no config row is left
    # untouched: no run, and no config is auto-created for it.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")

    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": ["*"]}):
        planned = await _run_activity()

    assert all(p.team_id != ateam.id for p in planned)
    config_count = await database_sync_to_async(SignalScoutConfig.all_teams.filter(team_id=ateam.id).count)()
    assert config_count == 0


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_explicit_id_still_seeds_a_config_less_team(ateam):
    # The contrast to the wildcard case: an explicitly-listed id IS force-provisioned — the tick
    # seeds a config for its scout skill and dispatches it, even with no pre-existing config row.
    # (Canonical sync is stubbed to a no-op, so only the hand-authored skill exists → exactly one
    # config is seeded.)
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")

    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": [ateam.id]}):
        planned = await _run_activity()

    assert any(p.team_id == ateam.id and p.skill_name == "signals-scout-errors" for p in planned)
    config_count = await database_sync_to_async(SignalScoutConfig.all_teams.filter(team_id=ateam.id).count)()
    assert config_count == 1


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
async def test_wildcard_honors_skip_team_ids(ateam):
    # The kill switch still bites under "*": a skipped team with an enabled config is drained.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=True)

    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": ["*"], "skip_team_ids": [ateam.id]}):
        planned = await _run_activity()

    assert all(p.team_id != ateam.id for p in planned)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.flag_off
@pytest.mark.parametrize("guaranteed_child,skip_child", [(True, False), (False, True)])
async def test_skip_canonicalizes_across_parent_child(ateam, aorganization, guaranteed_child, skip_child):
    # The kill switch must bite even when guaranteed_team_ids and skip_team_ids reference the same
    # project via DIFFERENT ids — one the child env, one the parent. Skip is applied after both sides
    # canonicalize to the parent, so a raw `explicit - skip` (which would miss the cross-id case)
    # can't let a hard-excluded project slip through and run.
    child = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCoordinatorSkipChild-{random.randint(1, 99999)}",
        parent_team=ateam,
    )
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-errors")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-errors", enabled=True)

    guaranteed_id = child.id if guaranteed_child else ateam.id
    skip_id = child.id if skip_child else ateam.id
    with patch(_PAYLOAD_PATH, return_value={"guaranteed_team_ids": [guaranteed_id], "skip_team_ids": [skip_id]}):
        planned = await _run_activity()

    assert all(p.team_id != ateam.id for p in planned)
    await sync_to_async(child.delete)()


# ── Enrollment metadata reflects the wildcard ──────


@pytest.mark.django_db
@pytest.mark.parametrize(
    "wildcard,in_explicit,in_skip,expected",
    [
        (True, False, False, True),  # wildcard → everyone enrolled
        (True, False, True, False),  # skip overrides the wildcard
        (False, True, False, True),  # explicit allowlist
        (False, False, False, False),  # not wildcard, not listed → not enrolled
    ],
)
def test_resolve_enrolled_wildcard(wildcard, in_explicit, in_skip, expected):
    # `_resolve_enrolled` short-circuits on direct set membership before any Team lookup, so a fake
    # id exercises every branch without needing a committed row.
    team_id = 999_999
    enrollment = Enrollment(
        wildcard=wildcard,
        explicit={team_id} if in_explicit else set(),
        skip={team_id} if in_skip else set(),
    )
    assert _resolve_enrolled(team_id, enrollment) is expected


# ── Global per-tick ceiling is flag-tunable ──────


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, MAX_RUNS_PER_TICK),  # no payload → code default
        ({}, MAX_RUNS_PER_TICK),  # absent key → code default
        ({"max_runs_per_tick_global": 5000}, 5000),  # raise the ceiling for a launch blast
        ({"max_runs_per_tick_global": 100}, 100),  # lower it to throttle
        ({"max_runs_per_tick_global": 0}, MAX_RUNS_PER_TICK),  # non-positive → default
        ({"max_runs_per_tick_global": "x"}, MAX_RUNS_PER_TICK),  # wrong type → default
        ({"max_runs_per_tick_global": True}, MAX_RUNS_PER_TICK),  # bool is not a valid int here
    ],
)
def test_resolve_global_max_runs_per_tick(payload, expected):
    assert _resolve_global_max_runs_per_tick(payload, MAX_RUNS_PER_TICK) == expected


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


@pytest.mark.django_db
def test_register_missing_configs_stamps_scout_category():
    # The "author a skill, get it on the Scouts tab" path: auto-registration stamps the server-owned
    # `category` so a custom scout authored via the skills API surfaces in the skills UI.
    org = Organization.objects.create(name="cat-stamp-org", is_ai_data_processing_approved=True)
    team = Team.objects.create(organization=org, name="cat-stamp-team")
    with team_scope(team.id, canonical=True):
        scout = _create_skill(team, "signals-scout-custom")
        helper = _create_skill(team, "custom-helper")
        assert scout.category == ""

        register_missing_configs(team.id)

        scout.refresh_from_db()
        helper.refresh_from_db()
        assert scout.category == "scout"
        # Non-scout skills are left untouched.
        assert helper.category == ""


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

    with patch("products.signals.backend.scout_harness.team_limits.MAX_RUNS_PER_TEAM_PER_TICK", 2):
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


# ── Fleet-wide default config via the flag payload (default_team_config) ──────────


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"default_team_config": {"max_runs_per_tick": 1}}, {"max_runs_per_tick": 1}),
        ('{"default_team_config": {"max_runs_per_tick": 2}}', {"max_runs_per_tick": 2}),  # JSON string payload
        ({"default_team_config": "nope"}, {}),  # wrong type → empty
        ({}, {}),  # absent key → no fleet default
        (None, {}),  # no payload → no fleet default
    ],
)
@pytest.mark.flag_off
def test_default_team_config_parses_payload(payload, expected):
    with patch(_PAYLOAD_PATH, return_value=payload):
        assert _default_team_config(_read_flag_payload()) == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "team_override_cap,expected_names",
    [
        # No per-team entry → the fleet-wide default_team_config (cap 1) binds.
        (None, ["signals-scout-most"]),
        # A valid per-team override beats the fleet default, so all three dispatch.
        (3, ["signals-scout-least", "signals-scout-mid", "signals-scout-most"]),
        # An invalid per-team override falls through to the fleet default (cap 1).
        ("nope", ["signals-scout-most"]),
    ],
)
async def test_default_team_config_resolution(ateam, team_override_cap, expected_names):
    # A fleet-wide `default_team_config` caps every enrolled team at 1/tick; a per-team
    # `team_configs` override takes precedence when present and valid, else the fleet default
    # still binds. Three scouts due (10h/5h/2h overdue) make the resolved cap observable.
    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _payload(*_a, **_k):
        payload: dict[str, Any] = {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"max_runs_per_tick": 1},
        }
        if team_override_cap is not None:
            payload["team_configs"] = {str(ateam.id): {"max_runs_per_tick": team_override_cap}}
        return payload

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    assert sorted(p.skill_name for p in planned) == sorted(expected_names)


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


# ── Seed posture via the flag (enabled_skills allowlist + interval) ───────────────


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "default_cfg,team_cfg,skills,expected_enabled",
    [
        # An allowlist enables only the listed canonical scout; the rest seed disabled.
        # (error-tracking / surveys are real on-disk canonical names, so the tag gates them.)
        (
            {"enabled_skills": ["signals-scout-general"]},
            None,
            [("signals-scout-general", True), ("signals-scout-error-tracking", True), ("signals-scout-surveys", True)],
            {"signals-scout-general": True, "signals-scout-error-tracking": False, "signals-scout-surveys": False},
        ),
        # No allowlist → every scout enables (back-compat, unchanged from before seed posture).
        (
            {},
            None,
            [("signals-scout-general", True), ("signals-scout-error-tracking", True)],
            {"signals-scout-general": True, "signals-scout-error-tracking": True},
        ),
        # A per-team override widens the fleet default for one team (close-partner case).
        (
            {"enabled_skills": ["signals-scout-general"]},
            {"enabled_skills": ["signals-scout-general", "signals-scout-error-tracking"]},
            [("signals-scout-general", True), ("signals-scout-error-tracking", True), ("signals-scout-surveys", True)],
            {"signals-scout-general": True, "signals-scout-error-tracking": True, "signals-scout-surveys": False},
        ),
        # A malformed per-team override falls back to the fleet default, not "no allowlist".
        (
            {"enabled_skills": ["signals-scout-general"]},
            {"enabled_skills": "signals-scout-general"},
            [("signals-scout-general", True), ("signals-scout-error-tracking", True)],
            {"signals-scout-general": True, "signals-scout-error-tracking": False},
        ),
        # A hand-authored custom scout (no seeded_by tag) auto-enables even under an allowlist.
        (
            {"enabled_skills": ["signals-scout-general"]},
            None,
            [("signals-scout-general", True), ("signals-scout-custom", False)],
            {"signals-scout-general": True, "signals-scout-custom": True},
        ),
        # A duplicated canonical scout keeps the seeded_by tag but on a non-canonical name, so it's
        # treated as custom and still auto-enables (not gated by the allowlist).
        (
            {"enabled_skills": ["signals-scout-general"]},
            None,
            [("signals-scout-general", True), ("signals-scout-general-copy", True)],
            {"signals-scout-general": True, "signals-scout-general-copy": True},
        ),
    ],
)
async def test_seed_posture_enabled_map(ateam, default_cfg, team_cfg, skills, expected_enabled):
    # Which scouts seed enabled vs disabled, across allowlist / no-allowlist / per-team-override /
    # malformed-override / custom-scout / duplicated-scout scenarios. `skills` is
    # (name, seeded_with_harness_tag) pairs; only a tag AND an on-disk canonical name = gated.
    for name, seeded in skills:
        await database_sync_to_async(_create_skill)(ateam, name, seeded=seeded)

    def _payload(*_a, **_k):
        payload: dict[str, Any] = {"guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS]}
        if default_cfg:
            payload["default_team_config"] = default_cfg
        if team_cfg is not None:
            payload["team_configs"] = {str(ateam.id): team_cfg}
        return payload

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        await _run_activity()

    rows = await database_sync_to_async(
        lambda: {c.skill_name: c.enabled for c in SignalScoutConfig.all_teams.filter(team_id=ateam.id)}
    )()
    assert rows == expected_enabled


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "interval,expected",
    [
        (1440, 1440),  # in-bounds cadence is stamped on the auto-enabled scout
        (20, None),  # below the 30-min model floor → ignored, model default kept
        (99999, None),  # above the 43200-min ceiling → ignored, model default kept
    ],
)
async def test_seed_enabled_interval_validates_bounds(ateam, interval, expected):
    # enabled_interval_minutes sets the cadence on allowlisted scouts, but only within the model's
    # 30–43200 bounds (get_or_create bypasses validators); out-of-range falls back to the default.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-general")

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"enabled_skills": ["signals-scout-general"], "enabled_interval_minutes": interval},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        await _run_activity()

    general = await database_sync_to_async(
        lambda: SignalScoutConfig.all_teams.get(team_id=ateam.id, skill_name="signals-scout-general")
    )()
    assert general.enabled is True
    if expected is not None:
        assert general.run_interval_minutes == expected
    else:
        # Unchanged from the model default (not the out-of-range value).
        assert general.run_interval_minutes != interval


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_seed_launch_cadence_stamped_on_disabled_canonical(ateam):
    # Option B: a canonical scout that seeds DISABLED under the allowlist still gets the launch
    # cadence stamped, so when the user later toggles it on it runs at the flag cadence, not the
    # model default. The launch cadence here (720) is deliberately distinct from the 1440 model
    # default so the assertion proves the flag value was stamped, not the fallback. general is
    # allowlisted (enabled); error-tracking is gated (disabled).
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-general")
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-error-tracking")

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {
                "enabled_skills": ["signals-scout-general"],
                "enabled_interval_minutes": 720,
            },
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        await _run_activity()

    rows = await database_sync_to_async(
        lambda: {
            c.skill_name: (c.enabled, c.run_interval_minutes)
            for c in SignalScoutConfig.all_teams.filter(team_id=ateam.id)
        }
    )()
    assert rows["signals-scout-general"] == (True, 720)
    # Disabled, but already on the flag cadence — so enabling it later doesn't fall back to the
    # 1440 model default.
    assert rows["signals-scout-error-tracking"] == (False, 720)


# ── Per-scout holdback denylist (withheld_skills) ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_withheld_scout_not_seeded_or_planned(ateam):
    # A scout on the fleet-wide `withheld_skills` default is never seeded a config and never
    # planned for a non-allowlisted team — the hard holdback. general is unaffected.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-general")
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-error-tracking")

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    seeded = await database_sync_to_async(
        lambda: set(SignalScoutConfig.all_teams.filter(team_id=ateam.id).values_list("skill_name", flat=True))
    )()
    assert "signals-scout-error-tracking" not in seeded
    assert "signals-scout-general" in seeded
    assert {p.skill_name for p in planned if p.team_id == ateam.id} == {"signals-scout-general"}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_withheld_scout_not_planned_even_when_config_enabled(ateam):
    # Belt-and-suspenders: a team that already has the scout enabled (e.g. previously allowed, or
    # self-enabled) still doesn't dispatch it once withheld — the dispatch gate, not just seeding.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-error-tracking")
    await database_sync_to_async(_create_config)(ateam, "signals-scout-error-tracking", enabled=True)

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    assert all(p.skill_name != "signals-scout-error-tracking" for p in planned)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_team_override_releases_withheld_scout(ateam):
    # The dogfood case: error-tracking is withheld fleet-wide, but this team's `team_configs`
    # override sets `withheld_skills: []`, so the scout seeds, enables, and plans for it.
    await database_sync_to_async(_create_skill)(ateam, "signals-scout-error-tracking")

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"withheld_skills": ["signals-scout-error-tracking"]},
            "team_configs": {str(ateam.id): {"withheld_skills": []}},
        }

    with patch(_PAYLOAD_PATH, side_effect=_payload):
        planned = await _run_activity()

    config = await database_sync_to_async(
        lambda: SignalScoutConfig.all_teams.get(team_id=ateam.id, skill_name="signals-scout-error-tracking")
    )()
    assert config.enabled is True
    assert {p.skill_name for p in planned if p.team_id == ateam.id} == {"signals-scout-error-tracking"}


# ── Per-team daily run budget (max_runs_per_day) ──────────────────────────────────


@pytest.mark.parametrize(
    "team_configs,default_cfg,expected",
    [
        ({}, {}, None),  # nothing set → unbounded (only the per-tick cap binds)
        ({}, {"max_runs_per_day": 3}, 3),  # fleet default binds
        ({7: {"max_runs_per_day": 10}}, {"max_runs_per_day": 3}, 10),  # per-team override wins
        ({7: {"max_runs_per_day": "nope"}}, {"max_runs_per_day": 3}, 3),  # malformed team → fleet default
        ({}, {"max_runs_per_day": 0}, None),  # non-positive → falls through to the constant (None)
        ({}, {"max_runs_per_day": True}, None),  # bool rejected
    ],
)
def test_resolve_max_runs_per_day(team_configs, default_cfg, expected):
    assert _resolve_max_runs_per_day(7, team_configs, default_cfg) == expected


@pytest.mark.parametrize(
    "team_configs,default_cfg,expected",
    [
        ({}, {}, set()),  # nothing set → nothing withheld
        ({}, {"withheld_skills": ["signals-scout-error-tracking"]}, {"signals-scout-error-tracking"}),  # fleet default
        # per-team override REPLACES the default list (here: release the full fleet to a dogfooder)
        ({7: {"withheld_skills": []}}, {"withheld_skills": ["signals-scout-error-tracking"]}, set()),
        # per-team override can withhold a different scout than the default
        (
            {7: {"withheld_skills": ["signals-scout-logs"]}},
            {"withheld_skills": ["signals-scout-error-tracking"]},
            {"signals-scout-logs"},
        ),
        # malformed team value (not a list of strings) falls through to the fleet default
        (
            {7: {"withheld_skills": "nope"}},
            {"withheld_skills": ["signals-scout-error-tracking"]},
            {"signals-scout-error-tracking"},
        ),
        (
            {7: {"withheld_skills": [1, 2]}},
            {"withheld_skills": ["signals-scout-error-tracking"]},
            {"signals-scout-error-tracking"},
        ),
    ],
)
def test_resolve_withheld_skills(team_configs, default_cfg, expected):
    assert _resolve_withheld_skills(7, team_configs, default_cfg) == expected


def _due_run(team_id: int, skill_name: str, overdue_s: float) -> _DueRun:
    return _DueRun(overdue_s=overdue_s, config_pk=skill_name, team_id=team_id, skill_name=skill_name)


@pytest.mark.parametrize(
    "default_cfg,runs_today,due_skills,expected",
    [
        # Budget 3, 2 already run today → 1 slot left, so only the most-overdue dispatches (the
        # per-tick cap of 50 is nowhere near binding).
        (
            {"max_runs_per_day": 3},
            {7: 2},
            [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)],
            ["signals-scout-most"],
        ),
        # Budget fully spent → 0 runs this tick; the empty team must not crash the round-robin.
        ({"max_runs_per_day": 3}, {7: 3}, [("signals-scout-most", 10)], []),
        # Pre-existing over-run (runs_today > budget) → still 0, no negative cap.
        ({"max_runs_per_day": 3}, {7: 5}, [("signals-scout-most", 10)], []),
        # No daily budget set → historical behaviour: every due run (within the per-tick cap) goes.
        ({}, {7: 999}, [("signals-scout-a", 1), ("signals-scout-b", 2)], ["signals-scout-a", "signals-scout-b"]),
    ],
)
def test_daily_budget_allocation(default_cfg, runs_today, due_skills, expected):
    due = [_due_run(7, name, hours * 3600) for name, hours in due_skills]
    selected = _allocate_tick_budget(due, {}, default_cfg, runs_today)
    assert sorted(d.skill_name for d in selected) == sorted(expected)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_daily_budget_bounds_dispatch_end_to_end(ateam):
    # End-to-end through the activity: fleet daily budget 2, team already ran once today (the
    # trailing-24h count is stubbed to 1) → only 1 slot left, so the single most-overdue scout
    # dispatches regardless of the per-tick cap.
    now = timezone.now()
    for name, hours in [("signals-scout-most", 10), ("signals-scout-mid", 5), ("signals-scout-least", 2)]:
        await database_sync_to_async(_create_skill)(ateam, name)
        await database_sync_to_async(_create_config)(
            ateam, name, enabled=True, run_interval_minutes=60, last_run_at=now - timedelta(hours=hours)
        )

    def _payload(*_a, **_k):
        return {
            "guaranteed_team_ids": [int(t) for t in _FLAGGED_TEAM_IDS],
            "default_team_config": {"max_runs_per_day": 2},
        }

    with (
        patch(_PAYLOAD_PATH, side_effect=_payload),
        patch(
            "products.signals.backend.temporal.agentic.scout_coordinator._runs_today_by_team",
            return_value={ateam.id: 1},
        ),
    ):
        planned = await _run_activity()

    assert [p.skill_name for p in planned] == ["signals-scout-most"]


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
