from __future__ import annotations

import json
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from uuid import UUID

from django.db.models import Case, DateTimeField, Q, Value, When
from django.utils import timezone

import structlog
from croniter import CroniterError, croniter
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalScoutBackgroundBand, SignalScoutConfig
from products.signals.backend.report_check_execution import run_due_report_checks
from products.signals.backend.scout_harness.config_registry import (
    MAX_RUN_INTERVAL_MINUTES,
    MIN_RUN_INTERVAL_MINUTES,
    canonical_operational_skill_names,
    enabled_scout_count,
    live_scout_skill_names,
    operational_configs_needing_reconcile,
    reconcile_operational_configs,
    register_missing_configs,
)
from products.signals.backend.scout_harness.lazy_seed import (
    canonical_config_tags_for,
    canonical_display_name_for,
    canonical_skill_names,
    discover_canonical_skills,
    sync_canonical_skills,
)
from products.signals.backend.scout_harness.limits import (
    AUTO_PAUSE_PROBE_INTERVAL_S,
    COORDINATOR_INTERVAL_MINUTES,
    DISPATCH_BATCH_INTERVAL_SECONDS,
    DISPATCH_SMEAR_SECONDS,
    DUE_GRACE_SECONDS,
    dispatch_ticks_per_interval,
)

# Per-team cap resolution + the flag-payload read live in the temporalio-free `team_limits` module
# so the HTTP metadata surface can share them. Imported by name so the planning code below calls
# them unqualified and tests can patch them on this module.
from products.signals.backend.scout_harness.team_limits import (
    DAILY_BUDGET_WINDOW,
    BackgroundEnrollment,
    Enrollment,
    _canonicalize_team_config_keys,
    _default_team_config,
    _parse_background,
    _parse_enrollment,
    _read_flag_payload,
    _resolve_dispatch_smear_seconds,
    _resolve_global_max_runs_per_tick,
    _resolve_max_runs_per_day,
    _resolve_max_runs_per_tick,
    _resolve_slot_aligned_dispatch,
    _resolve_withheld_skills,
    _runs_today_by_team,
    _team_configs,
    background_sample_bucket,
    resolve_max_enabled_scouts,
)
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutWorkflow
from products.signals.backend.temporal.metrics import (
    COORDINATOR_DISPATCH_DEDUPED,
    COORDINATOR_DISPATCH_STARTED,
    increment_coordinator_dispatch,
    increment_coordinator_tick,
)
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

# Hard cap on dispatches per tick. The cost bound: when more scouts are due than this,
# we run the most-overdue first and the rest catch up next tick (a poor-man's queue).
# Set generously for now while scouts roll out to more teams — the per-team tick cap and
# round-robin allocation do the day-to-day fairness work; this is the global ceiling.
MAX_RUNS_PER_TICK = 1000

# The tick grid itself (`COORDINATOR_INTERVAL_MINUTES`, `DUE_GRACE_SECONDS`,
# `dispatch_ticks_per_interval`) lives in `scout_harness/limits.py` so the failure breaker can
# size lanes off the cadence dispatch actually produces; it is imported above.
TICK_SECONDS = COORDINATOR_INTERVAL_MINUTES * 60


@dataclass
class PlannedRun:
    """One unit of fan-out: a single (team, skill) pair the coordinator will trigger."""

    team_id: int
    skill_name: str


@dataclass
class FetchEnabledRunsInput:
    """No fields today; placeholder for future filters (team allowlist, dry-run flags)."""

    pass


@frozen
class FetchEnabledRunsOutput:
    planned_runs: list[PlannedRun]
    dispatch_smear_seconds: int = 0


@frozen
class StampDispatchedRunsInput:
    """The (team, skill) runs whose child workflow was dispatched this batch, the tick's own
    start time to anchor their stamps on (`None` falls back to the wall clock), and how that
    batch split between freshly started children and dedupe-skipped ones."""

    dispatched_runs: list[PlannedRun]
    dispatched_at: datetime | None = None
    started_count: int = 0
    deduped_count: int = 0


@dataclass
class CoordinatorWorkflowInput:
    """Placeholder input for forward-compat (e.g. future dry-run / debug flags)."""

    pass


@dataclass
class CoordinatorWorkflowOutput:
    planned_count: int
    started_count: int
    skipped_count: int


@frozen
class RunDueChecksInput:
    """No fields today; the executor reads its own bounds."""


@frozen
class RunDueChecksOutput:
    expired: int
    passed: int
    failed: int
    errored: int
    # Defaulted so a workflow history written before the agent lane existed still decodes.
    dispatched: int = 0
    deferred: int = 0


@activity.defn
async def run_due_signal_report_checks_activity(_input: RunDueChecksInput) -> RunDueChecksOutput:
    """Advance every report check due this tick.

    Rides the coordinator rather than a schedule of its own: soak windows are days, so tick
    granularity is ample, and a deterministic check costs one cached Trends query with no sandbox
    and no scout enrolment. An `agent` check is dispatched here as a scout run and answers itself
    later, so this activity never waits on one.
    """
    async with Heartbeater():
        summary = await database_sync_to_async(run_due_report_checks, thread_sensitive=False)()
    return RunDueChecksOutput(
        expired=summary.expired,
        passed=summary.passed,
        failed=summary.failed,
        errored=summary.errored,
        dispatched=summary.dispatched,
        deferred=summary.deferred,
    )


@activity.defn
async def fetch_enabled_signals_scout_runs_activity(
    _input: FetchEnabledRunsInput,
) -> FetchEnabledRunsOutput:
    """Resolve the set of (team, skill) runs to dispatch this tick.

    Scans dogfood teams (gated by the `signals-scout` flag), auto-registers a config row
    for any `signals-scout-*` skill missing one, and dispatches each enabled scout whose
    schedule is due — most-overdue first, capped at MAX_RUNS_PER_TICK.
    """
    async with Heartbeater():
        # Read the flag payload once, off the DB thread pool — the SDK call can block on a cold
        # cache, and database_sync_to_async's pool is sized for DB-bound work (mirrors the
        # asyncio.to_thread split in ai_observability/team_discovery.py). Enrollment and per-team
        # configs are derived from the same snapshot so they can't disagree across two reads.
        payload = await asyncio.to_thread(_read_flag_payload)
        enrollment = _parse_enrollment(payload)
        background = _parse_background(payload)
        team_configs = _team_configs(payload)
        default_team_config = _default_team_config(payload)
        # The global per-tick ceiling is flag-tunable (no deploy): resolve it here off the same
        # snapshot, falling back to the code constant. `MAX_RUNS_PER_TICK` is read at call time so
        # tests patching the module global still take effect.
        global_max_runs_per_tick = _resolve_global_max_runs_per_tick(payload, MAX_RUNS_PER_TICK)
        smear_seconds = _resolve_dispatch_smear_seconds(payload, DISPATCH_SMEAR_SECONDS)
        planned = await database_sync_to_async(_collect_planned_runs, thread_sensitive=False)(
            enrollment, team_configs, default_team_config, global_max_runs_per_tick, background
        )
    logger.info("signals_scout coordinator: planned runs", count=len(planned))
    increment_coordinator_tick(len(planned))
    return FetchEnabledRunsOutput(planned_runs=planned, dispatch_smear_seconds=smear_seconds)


@activity.defn
async def stamp_dispatched_signals_scout_runs_activity(
    stamp_input: StampDispatchedRunsInput,
) -> None:
    """Advance `last_run_at` for the configs whose child workflow was dispatched this batch.

    Split out of planning so the schedule only advances for scouts a child was actually
    launched for: if fan-out fails (or the coordinator dies) before dispatch, the config
    stays unstamped and re-dispatches next tick instead of being silently suppressed for a
    full interval. The trade is a rare double-run if this stamp fails after children started
    — far less harmful than a day of suppression, and bounded by the activity retry policy.
    Called once per dispatch batch, so a coordinator that dies mid-smear leaves only its
    undispatched batches unstamped rather than the whole tick.
    """
    async with Heartbeater():
        # Same off-the-DB-pool read as planning: the SDK call can block on a cold cache, and
        # `database_sync_to_async`'s pool is sized for DB-bound work.
        payload = await asyncio.to_thread(_read_flag_payload)
        slot_aligned = _resolve_slot_aligned_dispatch(payload)
        await database_sync_to_async(_stamp_dispatched_runs, thread_sensitive=False)(
            stamp_input.dispatched_runs, slot_aligned=slot_aligned, dispatched_at=stamp_input.dispatched_at
        )
    # Counted here rather than in the workflow so a replay cannot double-count it, and after the
    # stamp so a retried attempt counts the batch once.
    increment_coordinator_dispatch(COORDINATOR_DISPATCH_STARTED, stamp_input.started_count)
    increment_coordinator_dispatch(COORDINATOR_DISPATCH_DEDUPED, stamp_input.deduped_count)


def _dispatch_slot(config_pk: str, run_interval_minutes: int) -> int:
    """The config's stable slot within its interval, as a count of coordinator ticks.

    Derived from a digest of the config's primary key so it never moves: the same scout keeps the
    same slot across restarts, redeploys, and re-enrolments, and the fleet's slots are spread by
    the digest's uniformity rather than by whenever each scout happened to be enabled.
    """
    ticks_per_interval = dispatch_ticks_per_interval(run_interval_minutes)
    digest = hashlib.sha256(str(config_pk).encode("utf-8"), usedforsecurity=False).digest()
    return int.from_bytes(digest[:8], "big") % ticks_per_interval


def _slot_anchor(config_pk: str, run_interval_minutes: int, dispatched_at: datetime) -> datetime:
    """The schedule anchor to stamp: the config's own slot, at or before this tick.

    Stamping `timezone.now()` here instead made `last_run_at` absorb the tick's planning and
    fan-out latency, so the next due time crept later every run. Once that creep passed
    `DUE_GRACE_SECONDS` a scout missed its usual tick and re-anchored on the next one, merging its
    cohort into that tick's cohort. The bigger merged wave then took longer to fan out, which made
    the next slip more likely, so waves only ever grew.

    Snapping back to the config's own slot removes both halves of that. Latency never accumulates,
    because the anchor is a grid point rather than a measured time. A run deferred past its slot by
    a per-team cap or a missed tick anchors on the slot it was meant to have, so cohorts drift back
    together on the grid instead of ratcheting forward off it.

    The snapped anchor always lands in `(this tick - period, this tick]`, where the period is the
    scout's cadence from `dispatch_ticks_per_interval`. Once a scout is dispatched on its own slot the
    anchor is exactly that tick, so its cadence is the configured one forever after.

    Before then the anchor can sit up to one period back, which shortens that single gap and costs
    the scout ONE EXTRA RUN. The shift is permanent rather than repaid: the scout keeps its new
    phase and its normal cadence from there, so it never skips a later run to make up for the early
    one. Each scout pays it once, when it first lands on its slot, and again after an interval edit
    (which changes its period, and so its slot). Accepted deliberately: it buys a de-merge that
    needs no migration and no backfill command, and the extra runs spread across every tick in the
    period rather than landing in the wave this is meant to break up.
    """
    ticks_per_interval = dispatch_ticks_per_interval(run_interval_minutes)
    slot = _dispatch_slot(config_pk, run_interval_minutes)
    tick_index = int(dispatched_at.timestamp()) // TICK_SECONDS
    snapped_index = tick_index - ((tick_index - slot) % ticks_per_interval)
    return datetime.fromtimestamp(snapped_index * TICK_SECONDS, tz=UTC)


def _stamp_dispatched_runs(
    dispatched_runs: list[PlannedRun], *, slot_aligned: bool = True, dispatched_at: datetime | None = None
) -> None:
    """Sync bulk stamp. `.update()` bypasses save(), so this per-tick write never hits the
    activity log.

    `dispatched_at` is the tick's start time, not the moment this batch happens to run: a late
    batch would otherwise floor to the next tick index (re-anchoring those scouts by a whole
    period) and push a cron scout's croniter reference past an occurrence it should still serve.

    Rolling-interval scouts are stamped with their slot anchor (see `_slot_anchor`). Anchors differ
    per config, so they are applied through a single `CASE` expression rather than one `.update()`
    per anchor: at the global tick cap a per-anchor loop would be up to `MAX_RUNS_PER_TICK`
    sequential round trips inside an activity whose timeout is a minute, and a timeout there lands
    after the children have already launched. Two kinds of config are stamped with the wall clock
    instead:

    - A cron scout, because `_overdue_seconds` feeds `last_run_at` to croniter as the reference for
      the next slot. Cron slots are already absolute, so that path never had the drift, and moving
      the reference backwards could re-select the slot this dispatch just fulfilled.
    - A disabled config, which here is a lane the failure breaker paused and the coordinator is
      probing. Its `last_run_at` is the probe cooldown clock rather than a schedule anchor, so
      backdating it would shorten the cooldown the breaker is counting.
    """
    if not dispatched_runs:
        return
    now = dispatched_at or timezone.now()
    predicate = Q()
    for run in dispatched_runs:
        predicate |= Q(team_id=run.team_id, skill_name=run.skill_name)
    dispatched = SignalScoutConfig.all_teams.filter(predicate)
    if not slot_aligned:
        dispatched.update(last_run_at=now)
        return

    pks_by_anchor: dict[datetime, list[UUID]] = {}
    for pk, enabled, cron_schedule, interval_minutes in dispatched.values_list(
        "pk", "enabled", "run_cron_schedule", "run_interval_minutes"
    ):
        anchor = _slot_anchor(str(pk), interval_minutes, now) if enabled and not cron_schedule else now
        pks_by_anchor.setdefault(anchor, []).append(pk)
    if not pks_by_anchor:
        return
    dispatched.update(
        last_run_at=Case(
            *(When(pk__in=pks, then=Value(anchor)) for anchor, pks in pks_by_anchor.items()),
            default=Value(now),
            output_field=DateTimeField(),
        )
    )


@dataclass
class _DueRun:
    overdue_s: float
    config_pk: str
    team_id: int
    skill_name: str


def _collect_planned_runs(
    enrollment: Enrollment,
    team_configs: dict[int, dict] | None = None,
    default_team_config: dict | None = None,
    max_runs_per_tick: int | None = None,
    background: BackgroundEnrollment | None = None,
) -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via Django's per-thread connection mgmt.

    Takes the parsed enrollment (explicit allowlist + the `"*"` wildcard), the optional per-team
    config overrides, the fleet-wide default config, the resolved global per-tick ceiling, and the
    parsed `background` block — so the flag reads all stay off this DB pool.

    Background configs are dispatched only through `_collect_background_runs`, never through the
    participating-team loop, so the consent check and the background kill switch gate every one.
    """
    now = timezone.now()
    team_configs = _canonicalize_team_config_keys(team_configs or {})
    default_team_config = default_team_config or {}
    due: list[_DueRun] = []
    background_team_ids: set[int] = set()
    if background is not None:
        skipped_team_ids = _canonicalize_team_ids(enrollment.skip)
        background_team_ids = _canonicalize_team_ids(set(background.team_ids)) - skipped_team_ids
        try:
            # A hand-picked team keeps no band, so `team_ids` stays an override that bands never change.
            band_by_team = {
                team_id: band
                for team_id, band in _sampled_band_teams(background).items()
                if team_id not in background_team_ids and team_id not in skipped_team_ids
            }
            background_team_ids |= band_by_team.keys()
            _reconcile_background_configs(
                background, background_team_ids, band_by_team, team_configs, default_team_config
            )
        except Exception:
            logger.exception("signals_scout coordinator: background reconcile failed; continuing")
    paused_by_team = _breaker_paused_configs_by_team()
    reconcile_by_team = operational_configs_needing_reconcile() if enrollment.wildcard else {}
    for team, needs_seed in _participating_teams(enrollment, reconcile_team_ids=set(reconcile_by_team)):
        # Scouts held back from this team via the `withheld_skills` denylist (resolved most-
        # specific-first from this team's `team_configs` entry, then the fleet `default_team_config`):
        # skip seeding the skill, skip seeding/enabling a config, and skip dispatch.
        withheld_for_team = _resolve_withheld_skills(team.id, team_configs, default_team_config)
        if needs_seed:
            # Explicitly enrolled (a pinned / force-provisioned id): seed from nothing. The periodic
            # tick is the reconciliation path. `sync_canonical_skills(prune=True)` tombstones rows
            # whose canonical was removed from disk and propagates merged SKILL.md updates to
            # harness-seeded rows the team hasn't edited, so a content change rolls out within one
            # tick. Idempotent; a failure here doesn't abort the tick.
            try:
                sync_canonical_skills(team, prune=True, withheld_skill_names=withheld_for_team)
            except Exception:
                logger.exception(
                    "signals_scout coordinator: canonical skill sync failed for team; continuing",
                    team_id=team.id,
                )
            # This team's seed posture resolves like the tick cap: its own `team_configs` override
            # layered over the fleet-wide `default_team_config`, most-specific first. Passing the
            # layers (not a shallow merge) lets `_resolve_seed_posture` fall back per key, so a
            # malformed per-team value doesn't clobber a valid fleet default.
            seed_config_layers = [team_configs.get(team.id) or {}, default_team_config]
            # `register_missing_configs` drops withheld skills from its return, so they're already
            # excluded from `live_skills` (and thus from dispatch below) as well as from seeding.
            live_skills = register_missing_configs(team.id, seed_config_layers, withheld_skill_names=withheld_for_team)
        else:
            # Wildcard-discovered (`"*"`): the team already self-seeded its configs through the
            # product-autonomy-gated UI / `sync` materialization, so skip the per-tick seed +
            # reconcile — that's what keeps the hot path cheap as self-enrollment scales to thousands
            # of teams. Read only the live scout skill names (cheap) so a config whose skill was
            # deleted/superseded isn't dispatched, and honor the holdback denylist. Central canonical
            # SKILL.md updates still reach these teams: the runner cold-starts with its own
            # `sync_canonical_skills` before loading the skill (runner.py), so a merged change lands
            # on the scout's NEXT RUN for any harness-seeded row the team hasn't forked. What the
            # per-tick skip drops is only the eager refresh on ticks where nothing dispatches, plus
            # the `prune=True` tombstoning of disk-deleted canonicals and first-appearance of
            # brand-new canonical scouts as rows — both rare, and both catch up on the team's next
            # `sync` (follow-up if needed: a slow fleet-wide prune/seed sweep off the dispatch path).
            live_skills = live_scout_skill_names(team.id, withheld_skill_names=withheld_for_team)
            # The one part of the reconcile the wildcard path still runs: an operational scout
            # that stays off stops the checks and validation that run on it. Only teams with a
            # row that needs it pay for the call, and a withheld scout is never a reason to call.
            if reconcile_by_team.get(team.id, set()) - withheld_for_team:
                _reconcile_wildcard_operational_configs(
                    team.id,
                    live_skills,
                    withheld_for_team,
                    [team_configs.get(team.id) or {}, default_team_config],
                )
        # Skip enabled configs whose skill was deleted or is no longer the
        # latest version: dispatching them would spawn a child workflow that fails fast in
        # load_skill_for_run on every tick.
        for config in SignalScoutConfig.all_teams.filter(
            team_id=team.id, enabled=True, skill_name__in=live_skills
        ).exclude(managed_by=SignalScoutConfig.ManagedBy.BACKGROUND):
            overdue_s = _overdue_seconds(config, now, team.timezone_info)
            if overdue_s is None:
                continue
            due.append(_DueRun(overdue_s, str(config.pk), team.id, config.skill_name))
        due.extend(_collect_probe_runs(paused_by_team.get(team.id, []), live_skills, now))

    if background is not None and background.enabled:
        due.extend(_collect_background_runs(background, background_team_ids, team_configs, default_team_config, now))

    if not due:
        return []

    # Only count runs for teams that actually have a resolved daily budget — for the default
    # rollout (no `max_runs_per_day` set anywhere) this skips the aggregate query entirely.
    capped_team_ids = {
        d.team_id for d in due if _resolve_max_runs_per_day(d.team_id, team_configs, default_team_config) is not None
    }
    runs_today = _runs_today_by_team(capped_team_ids, now - DAILY_BUDGET_WINDOW)
    selected = _allocate_tick_budget(due, team_configs, default_team_config, runs_today, max_runs_per_tick)
    planned = [PlannedRun(team_id=d.team_id, skill_name=d.skill_name) for d in selected]
    # Stable order for predictable child-workflow ids within the tick.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    return planned


def _allocate_tick_budget(
    due: list[_DueRun],
    team_configs: dict[int, dict] | None = None,
    default_team_config: dict | None = None,
    runs_today: dict[int, int] | None = None,
    max_runs_per_tick: int | None = None,
) -> list[_DueRun]:
    """Apply the per-team and global tick caps fairly. Deterministic — no sampling.

    Each team's due runs are ordered most-overdue-first and trimmed to its effective per-team
    cap, then the global budget is filled round-robin across teams (one run per team per round) so
    a single team with many due scouts can't monopolize the tick. Deferred runs stay unstamped, so
    they're the most overdue next tick — a poor-man's queue, same catch-up semantics as before.

    The global budget is `max_runs_per_tick` (the flag-resolved ceiling the activity passes in),
    falling back to the `MAX_RUNS_PER_TICK` code constant for direct callers that don't supply one.

    The effective per-team cap is the tighter of two bounds: the per-tick cap
    (`_resolve_max_runs_per_tick`) and the day's remaining headroom under the per-team daily
    budget (`_resolve_max_runs_per_day` minus `runs_today`). The daily budget is what bounds a
    team to N runs/day regardless of how many scouts it enables or how short their intervals —
    the per-tick cap alone can only bound bursts (≤ cap × ticks/day).
    """
    team_configs = team_configs or {}
    default_team_config = default_team_config or {}
    runs_today = runs_today or {}
    global_cap = max_runs_per_tick if max_runs_per_tick is not None else MAX_RUNS_PER_TICK

    def _team_cap(team_id: int) -> int:
        per_tick = _resolve_max_runs_per_tick(team_id, team_configs, default_team_config)
        per_day = _resolve_max_runs_per_day(team_id, team_configs, default_team_config)
        if per_day is None:
            return per_tick
        # Day's remaining headroom caps this tick too: a team that's spent its daily budget gets
        # 0 this tick, no matter how many scouts are due. Counted runs exclude this tick's
        # not-yet-started dispatches; the per-tick cap bounds that brief window.
        remaining_today = max(0, per_day - runs_today.get(team_id, 0))
        return min(per_tick, remaining_today)

    by_team: dict[int, list[_DueRun]] = {}
    for d in due:
        by_team.setdefault(d.team_id, []).append(d)
    for team_id, runs in by_team.items():
        runs.sort(key=lambda d: (-d.overdue_s, d.skill_name))
        cap = _team_cap(team_id)
        if len(runs) > cap:
            if cap == 0:
                # The expected steady state once a team has spent its daily budget — info, not a
                # warning, so it doesn't read as a misconfiguration in alerting (it would otherwise
                # fire every tick for the rest of the 24h window).
                logger.info(
                    "signals_scout coordinator: team daily budget spent, deferring all due scouts",
                    team_id=team_id,
                    deferred=len(runs),
                )
            else:
                logger.warning(
                    "signals_scout coordinator: team over effective per-team cap, deferring overflow",
                    team_id=team_id,
                    due=len(runs),
                    cap=cap,
                )
            del runs[cap:]

    # Drop teams trimmed to zero (e.g. daily budget spent) so the round-robin's most-overdue-team
    # sort never indexes into an empty list.
    by_team = {team_id: runs for team_id, runs in by_team.items() if runs}

    # Count after per-team trimming — that's the real candidate pool the global cap defers
    # against, so the warning doesn't fire on runs already dropped by the per-team caps.
    total_after_team_caps = sum(len(runs) for runs in by_team.values())
    if total_after_team_caps > global_cap:
        logger.warning(
            "signals_scout coordinator: more due than cap, deferring overflow",
            due=total_after_team_caps,
            cap=global_cap,
        )

    # Most-overdue team first, team id as the deterministic tiebreak.
    team_order = sorted(by_team, key=lambda t: (-by_team[t][0].overdue_s, t))
    selected: list[_DueRun] = []
    # Lists are already trimmed to each team's cap, so the longest list is exactly the number
    # of rounds needed — this naturally covers a team with a raised override too.
    max_rounds = max((len(runs) for runs in by_team.values()), default=0)
    for round_idx in range(max_rounds):
        if len(selected) >= global_cap:
            break
        for team_id in team_order:
            runs = by_team[team_id]
            if round_idx >= len(runs):
                continue
            selected.append(runs[round_idx])
            if len(selected) >= global_cap:
                break
    return selected


def _canonicalize_team_ids(ids: set[int]) -> set[int]:
    """Map team ids to their canonical parent project id (child env → parent), dropping ids with no
    `Team` row. Mirrors `_canonicalize_team_config_keys` / `_is_team_enrolled` so enrollment,
    configs, and dispatch all key on the same project id."""
    if not ids:
        return set()
    return {
        (parent_id or team_id)
        for team_id, parent_id in Team.objects.filter(id__in=ids).values_list("id", "parent_team_id")
    }


def _reconcile_wildcard_operational_configs(
    team_id: int, live_skills: set[str], withheld_skill_names: frozenset[str] | set[str], seed_config_layers: list[dict]
) -> None:
    """Run `reconcile_operational_configs` for one wildcard team. A failure does not abort the tick."""
    try:
        reconcile_operational_configs(
            team_id,
            canonical_operational_skill_names(team_id) & live_skills,
            withheld_skill_names,
            # Resolved here, because the reconcile holds row locks and must not read the flag.
            max_enabled_scouts=resolve_max_enabled_scouts(seed_config_layers),
        )
    except Exception:
        logger.exception(
            "signals_scout coordinator: operational reconcile failed for team; continuing",
            team_id=team_id,
        )


def _participating_teams(enrollment: Enrollment, reconcile_team_ids: set[int] | None = None) -> list[tuple[Team, bool]]:
    """Resolve enrollment to canonical `Team`s to run scouts on, each tagged `needs_seed`.

    Two ways a team participates:
    - explicit `guaranteed_team_ids` (skip removed) → force-provisioned: `needs_seed=True`, so the
      tick seeds canonical skills + registers configs from nothing (the pinned internal projects).
      Adding an id in the flag UI enrolls it on the next tick with no manual seed; removing it (or
      listing it in `skip_team_ids`) drains it.
    - the `"*"` wildcard → every team that already has an enabled `SignalScoutConfig`
      (`needs_seed=False`): it self-enrolled through the product-autonomy-gated UI, so it already
      has configs and the tick skips the expensive seed/reconcile for it. If a team is in both, the
      explicit tag wins (it gets the seed pass).
      `reconcile_team_ids` joins the wildcard set too: a team whose only scouts are operational
      ones the harness left off has no enabled config, and it must still reach the reconcile.
    Child envs canonicalize to their parent project; `skip_team_ids` is removed from both sets.
    Skip is subtracted AFTER canonicalizing both sides, so listing a child env in `guaranteed_team_ids`
    and its parent project in `skip_team_ids` (or the reverse) still hard-excludes the project — the
    raw ids differ but their canonical parent matches.
    """
    skip_canonical = _canonicalize_team_ids(enrollment.skip)
    explicit = _canonicalize_team_ids(enrollment.explicit) - skip_canonical

    wildcard_ids: set[int] = set()
    if enrollment.wildcard:
        # Config rows persist under the canonical parent team, so these ids are already canonical.
        # Breaker-paused configs keep the team enrolled even when nothing else is enabled: a
        # wildcard team whose only scout tripped the breaker would otherwise drop out of
        # participation entirely, and the recovery probe it was promised could never dispatch.
        wildcard_ids = set(
            SignalScoutConfig.all_teams.filter(
                Q(enabled=True)
                | Q(
                    status=SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
                    pause_reason=SignalScoutConfig.PauseReason.REPEATED_FAILURES,
                )
            )
            .exclude(managed_by=SignalScoutConfig.ManagedBy.BACKGROUND)
            .values_list("team_id", flat=True)
            .distinct()
        )
        wildcard_ids |= reconcile_team_ids or set()
    wildcard_ids -= skip_canonical
    wildcard_ids -= explicit  # explicit wins the tag — it gets the seed pass below

    all_ids = explicit | wildcard_ids
    if not all_ids:
        return []
    teams = {team.id: team for team in Team.objects.filter(id__in=all_ids)}
    return [(teams[team_id], team_id in explicit) for team_id in sorted(all_ids) if team_id in teams]


def _breaker_paused_configs_by_team() -> dict[int, list[SignalScoutConfig]]:
    """One cross-team fetch of every lane the failure-streak breaker has paused, keyed by team.

    Deliberately a single fleet-wide query hoisted out of `_collect_planned_runs`'s per-team
    loop: breaker trips are rare, so a per-team lookup would be one mostly-empty round-trip per
    participating team per tick. The filter is reason-scoped — only the breaker's own pauses —
    so a human's pause or another writer's is never fetched, let alone probed. Genuinely
    cross-team, which is what `all_teams` is for; per-team scoping happens at the call site.
    """
    paused_by_team: dict[int, list[SignalScoutConfig]] = {}
    paused = SignalScoutConfig.all_teams.filter(
        status=SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
        pause_reason=SignalScoutConfig.PauseReason.REPEATED_FAILURES,
    ).exclude(managed_by=SignalScoutConfig.ManagedBy.BACKGROUND)
    for config in paused:
        paused_by_team.setdefault(config.team_id, []).append(config)
    return paused_by_team


def _collect_probe_runs(paused_configs: list[SignalScoutConfig], live_skills: set[str], now: datetime) -> list[_DueRun]:
    """The half-open side of the failure-streak breaker: one probe per cooldown for paused lanes.

    A `(team, skill)` lane that fails every run still looks due every tick, and each dispatch
    takes a sandbox lease for the full runtime cap to produce nothing — so an unrecoverable lane
    costs a lease per interval indefinitely, with the only trace in the failure event stream.
    Once the runner trips the breaker (`runner._record_failure_streak` →
    `transition_status_by_system`), the pause syncs `enabled=False`, so the main dispatch query
    stops seeing the lane. This is the reason-scoped exception that keeps the breaker half-open:
    lanes paused with `repeated_failures` — never a human's pause, never another writer's,
    guaranteed by `_breaker_paused_configs_by_team`'s filter — get one probe per
    `AUTO_PAUSE_PROBE_INTERVAL_S`. A probe that succeeds resumes the lane
    (`runner._clear_failure_streak`); a failed probe restarts the cooldown through its own
    `last_run_at` stamp, with no extra bookkeeping.
    """
    probes: list[_DueRun] = []
    for config in paused_configs:
        if config.skill_name not in live_skills:
            continue
        # The cooldown runs from the later of the lane's last dispatch and the moment it was
        # paused. `last_run_at` alone is not enough: the run that trips the breaker was dispatched
        # while the lane was still enabled, so it was stamped with a slot anchor that can sit up to
        # a full period before the trip, and the cooldown would then read as already elapsed and
        # probe on the next tick. `status_changed_at` alone is not enough either, because a failed
        # probe leaves the status untouched and only `last_run_at` advances to restart the
        # cooldown. Neither set (possible only through manual row surgery) probes immediately
        # rather than never.
        cooldown_anchors = [moment for moment in (config.last_run_at, config.status_changed_at) if moment is not None]
        cooldown_elapsed_s = (
            (now - max(cooldown_anchors)).total_seconds() if cooldown_anchors else float(AUTO_PAUSE_PROBE_INTERVAL_S)
        )
        overdue_s = cooldown_elapsed_s - AUTO_PAUSE_PROBE_INTERVAL_S
        if overdue_s < 0:
            continue
        logger.info(
            "signals_scout coordinator: dispatching probe for auto-paused scout",
            team_id=config.team_id,
            skill_name=config.skill_name,
            consecutive_failure_count=config.consecutive_failure_count,
        )
        probes.append(_DueRun(overdue_s, str(config.pk), config.team_id, config.skill_name))
    return probes


def _ai_data_processing_approved(team: Team) -> bool:
    return team.organization.is_ai_data_processing_approved is True


def _sampled_band_teams(background: BackgroundEnrollment) -> dict[int, int]:
    """`team_id -> band` for each project that its band percent samples into the background lane.

    Reads nothing when every band is at 0 percent, which is the rollout default.
    """
    percents = {band: entry.percent for band, entry in background.bands.items() if entry.percent > 0}
    if not percents:
        return {}
    return {
        team_id: band
        for team_id, band in SignalScoutBackgroundBand.all_teams.filter(band__in=percents).values_list(
            "team_id", "band"
        )
        if background_sample_bucket(team_id) < percents[band]
    }


def _reconcile_background_configs(
    background: BackgroundEnrollment,
    listed_team_ids: set[int],
    band_by_team: dict[int, int],
    team_configs: dict[int, dict],
    default_team_config: dict,
) -> None:
    """Move background configs toward the `background` block of the flag payload.

    `listed_team_ids` holds the hand-picked `team_ids` and the band-sampled teams in `band_by_team`.
    Runs on a valid block only, because an unreadable block must never read as an empty list. The
    pause of departed teams runs even with `enabled` off, so an operator can drain one team without
    stopping the pilot. A lower band percent pauses through the same path, because the team leaves
    the listed set. Creation, resume, and band updates run only with `enabled` on.
    """
    _pause_departed_background_configs(listed_team_ids)
    if not background.enabled:
        return
    if background.skill_name not in canonical_skill_names():
        logger.warning(
            "signals_scout coordinator: background skill is not a canonical scout; skipping background setup",
            skill_name=background.skill_name,
        )
        return
    eligible = [
        team
        for team in Team.objects.filter(id__in=listed_team_ids).select_related("organization").order_by("id")
        if _ai_data_processing_approved(team)
        and background.skill_name not in _resolve_withheld_skills(team.id, team_configs, default_team_config)
    ]
    _resume_background_configs(background, eligible, team_configs, default_team_config)
    _sync_background_bands(background, eligible, band_by_team)
    _create_background_configs(background, eligible, band_by_team, team_configs, default_team_config)


def _pause_departed_background_configs(listed_team_ids: set[int]) -> None:
    """Pause every runnable background config whose team is no longer listed.

    `transition_status_by_system` refuses a row a person paused or another writer owns, so this
    only ever pauses what the background coordinator may still change.
    """
    departed = SignalScoutConfig.all_teams.filter(
        managed_by=SignalScoutConfig.ManagedBy.BACKGROUND,
        status__in=SignalScoutConfig.RUNNABLE_STATUSES,
    ).exclude(team_id__in=listed_team_ids)
    for config in departed:
        if config.transition_status_by_system(
            SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
            pause_reason=SignalScoutConfig.PauseReason.BACKGROUND_REMOVED,
        ):
            logger.info(
                "signals_scout coordinator: paused background scout for a team that left the list",
                team_id=config.team_id,
                skill_name=config.skill_name,
            )


def _resume_background_configs(
    background: BackgroundEnrollment,
    eligible_teams: list[Team],
    team_configs: dict[int, dict],
    default_team_config: dict,
) -> None:
    """Resume the background configs this coordinator paused, for teams that are listed again."""
    paused = SignalScoutConfig.all_teams.filter(
        team_id__in=[team.id for team in eligible_teams],
        skill_name=background.skill_name,
        managed_by=SignalScoutConfig.ManagedBy.BACKGROUND,
        status=SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
        pause_reason=SignalScoutConfig.PauseReason.BACKGROUND_REMOVED,
    )
    for config in paused:
        config.transition_status_by_system(
            SignalScoutConfig.Status.ACTIVE,
            pause_reason=SignalScoutConfig.PauseReason.BACKGROUND_REMOVED,
            max_enabled_scouts=resolve_max_enabled_scouts(
                [team_configs.get(config.team_id) or {}, default_team_config]
            ),
        )


def _background_interval(background: BackgroundEnrollment, band: int | None) -> int | None:
    """The interval a background config gets, or `None` to keep the model default."""
    interval = background.band_interval_minutes(band)
    if interval is not None and MIN_RUN_INTERVAL_MINUTES <= interval <= MAX_RUN_INTERVAL_MINUTES:
        return interval
    return None


def _sync_background_bands(
    background: BackgroundEnrollment,
    eligible_teams: list[Team],
    band_by_team: dict[int, int],
) -> None:
    """Keep the band of each background config current, and give a config its new band's interval.

    Only `managed_by=background` rows change, so a person who took a config over keeps their schedule.
    """
    stale = SignalScoutConfig.all_teams.filter(
        team_id__in=[team.id for team in eligible_teams],
        skill_name=background.skill_name,
        managed_by=SignalScoutConfig.ManagedBy.BACKGROUND,
    ).only("id", "team_id", "background_band")
    for config in stale:
        band = band_by_team.get(config.team_id)
        if config.background_band == band:
            continue
        # Without a configured interval, fall back to the model default rather than keep the old band's.
        interval = _background_interval(background, band)
        changes: dict = {
            "background_band": band,
            "run_interval_minutes": interval
            if interval is not None
            else SignalScoutConfig._meta.get_field("run_interval_minutes").default,
        }
        SignalScoutConfig.all_teams.filter(pk=config.pk, managed_by=SignalScoutConfig.ManagedBy.BACKGROUND).update(
            **changes
        )


def _create_background_configs(
    background: BackgroundEnrollment,
    eligible_teams: list[Team],
    band_by_team: dict[int, int],
    team_configs: dict[int, dict],
    default_team_config: dict,
) -> None:
    """Create one background config for the background skill on each listed team that has none.

    Seeds only the background skill, not the canonical catalog that `guaranteed_team_ids` seeds,
    and creates only this one config. A team that already has a config for the skill keeps it
    untouched, whoever created it. At most `max_new_teams_per_tick` teams are set up per tick.
    """
    has_config = set(
        SignalScoutConfig.all_teams.filter(
            team_id__in=[team.id for team in eligible_teams], skill_name=background.skill_name
        ).values_list("team_id", flat=True)
    )
    pending = [team for team in eligible_teams if team.id not in has_config]
    if not pending:
        return
    defaults: dict = {"managed_by": SignalScoutConfig.ManagedBy.BACKGROUND}
    if tags := canonical_config_tags_for(background.skill_name):
        defaults["tags"] = list(tags)
    if display_name := canonical_display_name_for(background.skill_name):
        defaults["display_name"] = display_name
    other_canonical_names = {canonical.name for canonical in discover_canonical_skills()} - {background.skill_name}

    created = 0
    for team in pending:
        if created >= background.max_new_teams_per_tick:
            break
        max_enabled = resolve_max_enabled_scouts([team_configs.get(team.id) or {}, default_team_config])
        if enabled_scout_count(team.id) >= max_enabled:
            logger.info(
                "signals_scout coordinator: team at enabled-scout cap, skipping background setup",
                team_id=team.id,
                cap=max_enabled,
            )
            continue
        try:
            sync_canonical_skills(team, withheld_skill_names=other_canonical_names)
        except Exception:
            logger.exception(
                "signals_scout coordinator: background skill seed failed for team; continuing",
                team_id=team.id,
            )
            continue
        band = band_by_team.get(team.id)
        team_defaults = {**defaults, "background_band": band}
        if (interval := _background_interval(background, band)) is not None:
            team_defaults["run_interval_minutes"] = interval
        _, was_created = SignalScoutConfig.objects.for_team(team.id).get_or_create(
            team_id=team.id, skill_name=background.skill_name, defaults=team_defaults
        )
        if was_created:
            created += 1
            logger.info(
                "signals_scout coordinator: created background scout config",
                team_id=team.id,
                skill_name=background.skill_name,
                background_band=band,
            )


def _collect_background_runs(
    background: BackgroundEnrollment,
    listed_team_ids: set[int],
    team_configs: dict[int, dict],
    default_team_config: dict,
    now: datetime,
) -> list[_DueRun]:
    """Due runs for background configs on listed teams whose organization approved AI data processing.

    Checks consent again at dispatch, because an organization can withdraw it after its config was
    created. Breaker-paused background configs get their probes here too, so no background run
    skips the consent check.
    """
    if not listed_team_ids:
        return []
    configs = SignalScoutConfig.all_teams.filter(
        Q(enabled=True)
        | Q(
            status=SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
            pause_reason=SignalScoutConfig.PauseReason.REPEATED_FAILURES,
        ),
        team_id__in=listed_team_ids,
        skill_name=background.skill_name,
        managed_by=SignalScoutConfig.ManagedBy.BACKGROUND,
    ).select_related("team__organization")
    live_team_ids = set(
        LLMSkill.objects.filter(
            team_id__in=listed_team_ids, name=background.skill_name, is_latest=True, deleted=False
        ).values_list("team_id", flat=True)
    )
    due: list[_DueRun] = []
    live_skills = {background.skill_name}
    for config in configs:
        if config.team_id not in live_team_ids or not _ai_data_processing_approved(config.team):
            continue
        if background.skill_name in _resolve_withheld_skills(config.team_id, team_configs, default_team_config):
            continue
        if not config.enabled:
            due.extend(_collect_probe_runs([config], live_skills, now))
            continue
        overdue_s = _overdue_seconds(config, now, config.team.timezone_info)
        if overdue_s is not None:
            due.append(_DueRun(overdue_s, str(config.pk), config.team_id, config.skill_name))
    return due


def _overdue_seconds(config: SignalScoutConfig, now: datetime, project_timezone: tzinfo) -> float | None:
    """Seconds past due, or None if not yet due. Never-run rolling schedules are maximally overdue."""
    if config.run_cron_schedule:
        # `schedule_changed_at` (stamped only on actual schedule edits — deliberately not
        # `updated_at`, which every emit/enabled save bumps) anchors a newly saved schedule so
        # selecting a future slot waits for that occurrence instead of immediately catching up
        # against a slot from before the edit. `created_at` covers never-edited rows.
        schedule_reference = max(
            reference
            for reference in (config.last_run_at, config.schedule_changed_at, config.created_at)
            if reference is not None
        )
        local_schedule_reference = schedule_reference.astimezone(project_timezone)
        try:
            # First occurrence strictly after the reference. Iterated in *naive* project-local
            # time and re-localized afterwards: tz-aware croniter preserves the absolute interval
            # across a DST change (shifting the local hour), but the contract here is wall-clock —
            # a 9am schedule stays 9am local through DST transitions.
            naive_slot = croniter(config.run_cron_schedule, local_schedule_reference.replace(tzinfo=None)).get_next(
                datetime
            )
            first_unfulfilled_slot = naive_slot.replace(tzinfo=project_timezone)
        except CroniterError:
            # The expression is serializer-validated on write, so this only fires on out-of-band
            # writes. Fall through to the rolling interval rather than killing the whole tick.
            logger.warning(
                "signals_scout_invalid_cron_schedule",
                config_id=str(config.pk),
                run_cron_schedule=config.run_cron_schedule,
            )
        else:
            if now < first_unfulfilled_slot:
                return None
            # Keep measuring from the first missed slot until dispatch so bounded coordinator ticks
            # cannot reset a deferred run's priority when the next scheduled slot arrives.
            return (now - first_unfulfilled_slot).total_seconds()

    if config.last_run_at is None:
        return float("inf")
    overdue = (now - config.last_run_at).total_seconds() - config.run_interval_minutes * 60
    return overdue if overdue >= -DUE_GRACE_SECONDS else None


@workflow.defn(name="run-signals-scout-coordinator")
class SignalsScoutCoordinatorWorkflow:
    """Coordinator: scans dogfood teams, fans out per-(team, skill) child runs for due scouts.

    Dispatch is fire-and-forget: each child is started with `ParentClosePolicy.ABANDON`
    so it outlives this workflow. Temporal's task queue + worker concurrency handles the
    throttling — if workers are saturated, the children just queue.

    The fan-out is paced rather than emitted in one burst: the planned runs are split into
    batches dispatched `DISPATCH_BATCH_INTERVAL_SECONDS` apart across a `dispatch_smear_seconds`
    window, so the fleet's runs are created over minutes instead of landing in the single minute
    of the tick. The window is bounded well under the tick and the schedule caps the workflow's
    execution at one tick interval, so `SKIP` still never collapses ticks; a coordinator is now
    alive for a meaningful fraction of every tick, though, so any later edit to this method needs
    a `workflow.patched()` gate (see `.claude/rules/temporal-workflow-versioning.md`) — this
    change itself is gated on `FetchEnabledRunsOutput.dispatch_smear_seconds` defaulting to 0.

    The schedule advances only after dispatch (not during planning) so a fan-out failure
    re-dispatches next tick rather than silently suppressing a scout for a full interval, and
    is stamped per batch so a coordinator that dies mid-smear leaves only its undispatched
    batches unstamped.

    Idempotency: child workflow IDs are deterministic per `(team_id, skill_name, tick_id)`,
    so a retried coordinator can't double-launch within a single tick. A separate
    skip-if-running guard inside the runner protects against tick-over-tick collisions.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorWorkflowInput:
        if not inputs:
            return CoordinatorWorkflowInput()
        loaded = json.loads(inputs[0])
        return CoordinatorWorkflowInput(**loaded)

    @workflow.run
    async def run(self, _input: CoordinatorWorkflowInput) -> CoordinatorWorkflowOutput:
        if workflow.patched("signals-report-checks-2026-09"):
            await workflow.execute_activity(
                run_due_signal_report_checks_activity,
                RunDueChecksInput(),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        fetch_result = await workflow.execute_activity(
            fetch_enabled_signals_scout_runs_activity,
            FetchEnabledRunsInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        planned_runs = fetch_result.planned_runs
        if not planned_runs:
            return CoordinatorWorkflowOutput(0, 0, 0)

        # `workflow_id` (not `run_id`) is the correct per-tick key. Temporal appends the
        # scheduled time to a schedule-started workflow's id, so each tick gets a
        # distinct `workflow_id` (`signals-scout-coordinator-schedule-<scheduled-time>`) —
        # unique across ticks, which is what lets a later tick relaunch the same (team, skill).
        # It's also stable across a coordinator retry/replay within the same tick (only
        # `run_id` changes on retry), so the deterministic child ids below + REJECT_DUPLICATE
        # dedupe a retry without re-launching. `run_id` would break that: a retry would mint
        # new child ids and double-launch.
        tick_id = workflow.info().workflow_id
        tick_started_at = workflow.info().start_time
        smear_seconds = max(0, fetch_result.dispatch_smear_seconds)
        smear_deadline = tick_started_at + timedelta(seconds=smear_seconds)
        batches = _dispatch_batches(planned_runs, smear_seconds)

        started = 0
        skipped = 0
        for batch_number, batch in enumerate(batches, start=1):
            dispatched: list[PlannedRun] = []
            batch_started = 0
            batch_deduped = 0
            for idx, planned in batch:
                if await _start_child(planned=planned, tick_id=tick_id, idx=idx):
                    batch_started += 1
                else:
                    batch_deduped += 1
                # Both branches mean a child for this (team, skill, tick) now exists (started, or
                # dedupe-skipped because a retry already started it) — so its schedule should
                # advance. A hard `start_child` error raises out of `_start_child` before reaching
                # here, leaving that config unstamped to re-dispatch next tick.
                dispatched.append(planned)

            started += batch_started
            skipped += batch_deduped

            # Stamp only after dispatch, so a fan-out failure can't suppress a scout for a day.
            await workflow.execute_activity(
                stamp_dispatched_signals_scout_runs_activity,
                StampDispatchedRunsInput(
                    dispatched_runs=dispatched,
                    dispatched_at=tick_started_at,
                    started_count=batch_started,
                    deduped_count=batch_deduped,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )

            if batch_number < len(batches) and workflow.now() < smear_deadline:
                await workflow.sleep(timedelta(seconds=DISPATCH_BATCH_INTERVAL_SECONDS))

        return CoordinatorWorkflowOutput(
            planned_count=len(planned_runs),
            started_count=started,
            skipped_count=skipped,
        )


def _dispatch_batches(planned_runs: list[PlannedRun], smear_seconds: int) -> list[list[tuple[int, PlannedRun]]]:
    """Split the tick's planned runs into the batches to dispatch one `DISPATCH_BATCH_INTERVAL_SECONDS`
    apart, each entry carrying its index in the full planned list so child ids stay stable.

    Strided rather than sliced contiguously: `planned_runs` is sorted by `(team_id, skill_name)`,
    so contiguous batches would put a whole team in one batch and make how late a team dispatches
    a permanent function of its id. A stride of 1 (`smear_seconds=0`, which is also what an
    in-flight coordinator replaying a pre-smear history resolves to) yields today's single batch
    in today's order.
    """
    indexed = list(enumerate(planned_runs))
    num_batches = max(1, min(smear_seconds // DISPATCH_BATCH_INTERVAL_SECONDS, len(indexed)))
    return [indexed[offset::num_batches] for offset in range(num_batches)]


async def _start_child(*, planned: PlannedRun, tick_id: str, idx: int) -> bool:
    """Fire-and-forget child dispatch. Returns True if started, False if dedupe-skipped.

    `REJECT_DUPLICATE` makes a re-dispatch of an already-started child for the same
    deterministic `(team, skill, tick, idx)` id raise `WorkflowAlreadyStartedError`
    whether that prior child is still running OR already closed — so a coordinator
    retry/replay within the same tick skips it instead of re-running it (`ALLOW_DUPLICATE`
    would re-launch a child that finished before the retry, double-running that team for
    the tick). Any other exception bubbles up: the coordinator's `RetryPolicy` re-dispatches
    idempotently because workflow IDs are deterministic.
    """
    child_id = _child_workflow_id(planned, tick_id, idx)
    try:
        await workflow.start_child_workflow(
            RunSignalsScoutWorkflow.run,
            RunSignalsScoutInput(
                team_id=planned.team_id,
                skill_name=planned.skill_name,
            ),
            id=child_id,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return True
    except WorkflowAlreadyStartedError:
        workflow.logger.info(
            "signals_scout coordinator: child already running, skipping",
            extra={"team_id": planned.team_id, "skill_name": planned.skill_name, "child_id": child_id},
        )
        return False


def _child_workflow_id(planned: PlannedRun, tick_id: str, idx: int) -> str:
    # Tick_id makes the ID unique across coordinator runs; idx disambiguates if a team
    # somehow ends up with the same skill twice in a tick (defense-in-depth — the
    # planning step already dedupes via sorted unique).
    safe_skill = planned.skill_name.replace(" ", "_")[:60]
    return f"signals-scout-run-{planned.team_id}-{safe_skill}-{tick_id}-{idx}"
