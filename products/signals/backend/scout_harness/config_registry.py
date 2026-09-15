"""Auto-registration of `SignalScoutConfig` rows for `signals-scout-*` skills.

A scout is a skill that has a `SignalScoutConfig` row. The row is the identity marker, so a
scout may carry any valid skill name.

The prefix still drives one thing: the "author a skill, get a scout" contract. Any
`signals-scout-*` `LLMSkill` on a team gets a row (default schedule, enabled) with no further
wiring. A bare-named skill needs the scout `create` endpoint, explicit registration, or the
create modal. The Temporal coordinator tick calls this so enrolled teams reconcile on schedule.
The HTTP surface deliberately does not: reads stay side-effect free, and explicit registration
goes through the write-scoped config `create` endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from croniter import CroniterError, croniter

from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.activity_logging.model_activity import ActivityTriggerContext

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import (
    HARNESS_SEEDED_BY,
    SCOUT_SKILL_CATEGORY,
    canonical_config_tags_for,
    canonical_config_write_scopes_for,
    canonical_skill_names,
    is_operational_scout,
)
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

# Mirror the `SignalScoutConfig.run_interval_minutes` model + serializer bounds (30–43200). A
# seed interval comes from arbitrary flag JSON and is written via `get_or_create`, which bypasses
# model validators — so an out-of-range value is validated here and treated as absent rather than
# persisted (a large enough int would otherwise raise a DB error and abort the coordinator tick).
MIN_RUN_INTERVAL_MINUTES = 30
MAX_RUN_INTERVAL_MINUTES = 43200

# Matches the `run_interval_minutes` floor: one scout may not occupy the coordinator more
# than once per 30 minutes, however the schedule is expressed.
CRON_MIN_GAP_SECONDS = MIN_RUN_INTERVAL_MINUTES * 60
# The column and the config API field cap; every writer applies it so a stored schedule fits.
CRON_SCHEDULE_MAX_LENGTH = 100
# Occurrences sampled by the min-gap check. Enough to expose sub-30-minute patterns
# (a `*/15` fires 96×/day) while staying trivially cheap for sparse schedules.
_CRON_SAMPLE_OCCURRENCES = 100

_OPERATIONAL_RECONCILE_JOB_TYPE = "signals_scout_operational_reconcile"


def cron_schedule_error(value: str) -> str | None:
    """Why `value` is not an acceptable scout cron schedule, or None when it is.

    The one rule every writer applies (the config API serializers and the suggestion producer), so a
    schedule stored anywhere can be run everywhere: croniter also accepts 6/7-field (seconds/years)
    forms and @-aliases, so the shape is restricted to plain five fields, and occurrences must keep
    the same 30-minute floor as `run_interval_minutes`.
    """
    expr = value.strip()
    if len(expr) > CRON_SCHEDULE_MAX_LENGTH:
        return f"Cron expressions must be at most {CRON_SCHEDULE_MAX_LENGTH} characters."
    if len(expr.split()) != 5 or not croniter.is_valid(expr):
        return "Not a valid five-field cron expression, e.g. '30 9 * * *' or '0 9 * * 1-5'."
    iterator = croniter(expr, datetime(2026, 1, 1, tzinfo=UTC))
    try:
        occurrences = [iterator.get_next(datetime) for _ in range(_CRON_SAMPLE_OCCURRENCES)]
    except CroniterError:
        # `is_valid` accepts syntactically valid calendars that never occur, like '0 0 31 2 *'.
        return "This schedule never matches a real date. Check the day and month fields."
    min_gap = min((later - earlier).total_seconds() for earlier, later in zip(occurrences, occurrences[1:]))
    if min_gap < CRON_MIN_GAP_SECONDS:
        return "Scheduled runs must be at least 30 minutes apart (the same floor as run_interval_minutes)."
    return None


def ensure_scout_category(team_id: int, skill_name: str | None = None) -> None:
    """Stamp `LLMSkill.category="scout"` on the team's scout skill rows.

    `category` is server-owned, so this is how custom scouts authored via the normal skills API
    get categorized — canonical scouts are already stamped at seed time (`lazy_seed`). Without it
    a freshly registered scout would schedule but stay off the skills UI's Scouts tab. Idempotent
    (skips already-stamped rows). Pass `skill_name` to stamp one scout (e.g. on explicit
    registration), or omit to reconcile every scout row for the team.

    The bulk pass keys on config rows, not on the name, so a bare-named scout reaches the Scouts
    tab too. Callers that create rows must run this after the creation, not before.
    """
    rows = LLMSkill.objects.filter(team_id=team_id, deleted=False).exclude(category=SCOUT_SKILL_CATEGORY)
    if skill_name is not None:
        rows = rows.filter(name=skill_name)
    else:
        rows = rows.filter(name__in=SignalScoutConfig.objects.for_team(team_id).values_list("skill_name", flat=True))
    # QuerySet.update() skips auto_now, but the shared marketplace version uses updated_at.
    rows.update(category=SCOUT_SKILL_CATEGORY, updated_at=timezone.now())


def enabled_scout_count(team_id: int, *, exclude_skill: str | None = None) -> int:
    """Count of enabled scout configs for the team — the quantity the per-team cap bounds.

    `exclude_skill` leaves one skill's own row out of the count, so re-asserting
    `enabled=True` on an already-enabled scout doesn't read as exceeding the cap.
    """
    queryset = SignalScoutConfig.objects.for_team(team_id).filter(enabled=True)
    if exclude_skill is not None:
        queryset = queryset.exclude(skill_name=exclude_skill)
    return queryset.count()


def _resolve_seed_posture(seed_config_layers: list[dict] | None) -> tuple[set[str] | None, int | None]:
    """Resolve the seed posture across ordered config layers, most-specific first.

    Each field is resolved independently: the first layer carrying a VALID value for that key
    wins; a layer whose value is absent or malformed falls through to the next — the same per-key
    fallback as `_resolve_max_runs_per_tick` does for the tick cap, so a typo'd per-team override
    doesn't silently drop the fleet default (e.g. a team passing `enabled_skills` as a string
    still inherits the fleet allowlist rather than enabling everything).

    Returns `(enabled_skills, enabled_interval_minutes)`:
    - `enabled_skills`: allowlist of canonical scouts that auto-enable on seed; the rest register
      disabled. `None` (no valid layer) means "no allowlist" — every scout enables, historical.
    - `enabled_interval_minutes`: cadence stamped on the auto-enabled rows, validated against the
      model's 30–43200 bounds; `None` keeps the model default.
    """
    layers = [layer for layer in (seed_config_layers or []) if isinstance(layer, dict)]

    enabled_skills: set[str] | None = None
    for layer in layers:
        raw_skills = layer.get("enabled_skills")
        if isinstance(raw_skills, list) and all(isinstance(s, str) for s in raw_skills):
            enabled_skills = {str(s) for s in raw_skills}
            break

    enabled_interval: int | None = None
    for layer in layers:
        raw_interval = layer.get("enabled_interval_minutes")
        if (
            isinstance(raw_interval, int)
            and not isinstance(raw_interval, bool)
            and MIN_RUN_INTERVAL_MINUTES <= raw_interval <= MAX_RUN_INTERVAL_MINUTES
        ):
            enabled_interval = raw_interval
            break

    return enabled_skills, enabled_interval


def live_scout_skill_names(
    team_id: int,
    withheld_skill_names: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Names of the team's configs whose skill is live (latest, non-deleted), minus the holdback set.

    Liveness means "the config's skill is live", so the read is keyed on config rows and a scout
    under any valid name is included. The coordinator dispatches only configs whose skill is in
    this set, so a config whose skill was deleted or superseded isn't run. Used on the wildcard
    (no-seed) dispatch path — a team that self-enrolled through the UI already has its configs, so
    the per-tick seed/reconcile is skipped and this cheap read is what still gates dispatch.

    The config names go in as a subquery, and the holdback is applied as an `exclude` on the same
    query, so the per-team gate stays one round trip. Keep it that way — this runs once per team
    on every tick.
    """
    rows = LLMSkill.objects.filter(
        team_id=team_id,
        name__in=SignalScoutConfig.objects.for_team(team_id).values_list("skill_name", flat=True),
        is_latest=True,
        deleted=False,
    )
    if withheld_skill_names:
        rows = rows.exclude(name__in=withheld_skill_names)
    return set(rows.values_list("name", flat=True))


def register_missing_configs(
    team_id: int,
    seed_config_layers: list[dict] | None = None,
    withheld_skill_names: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Auto-create a config for each scout skill lacking a row, honouring an optional seed posture.

    Idempotent — `get_or_create` keyed on the `(team, skill_name)` unique constraint, so
    concurrent callers (coordinator tick racing an API call) converge on one row.

    Returns the union of the live `signals-scout-*` skills scanned here and every live skill that
    already holds a config, so the caller can dispatch a bare-named scout and still skip a config
    whose skill is gone. The prefix scan drives auto-registration only; a bare-named scout is
    registered by the create endpoint, and this read is what keeps it dispatchable.

    `withheld_skill_names` is the per-team holdback denylist (resolved by the coordinator from
    the `signals-scout` flag's `withheld_skills` key). Withheld skills are dropped from the
    returned set before any work, so no config is seeded for them AND the coordinator (which
    dispatches only configs whose skill is in this return) never runs them — the second and
    third enforcement points of the holdback, after `sync_canonical_skills` keeps the skill row
    from being seeded at all. Belt-and-suspenders for the case where a row already exists (a team
    that was previously allowed): the scout stays visible but is never enabled or dispatched here.

    `seed_config_layers` are the team's flag config layers, most-specific first (its `team_configs`
    override, then the fleet `default_team_config`); `_resolve_seed_posture` resolves them per key.
    When an `enabled_skills` allowlist is in force, only those **canonical** (harness-seeded)
    scouts auto-enable (at `enabled_interval_minutes` if set) and the rest register disabled — the
    launch posture (e.g. general-only, once a day). Hand-authored **custom** scouts are never gated
    by the allowlist: "author a skill, get a scout" still auto-enables them, so a launch team's own
    scout isn't silently muted. With no allowlist, every scout enables at the model-default
    schedule. Either way, a scout disabled at seed stays visible and tunable but adds no spend.

    A canonical scout's `scout-tags` frontmatter is stamped on the row it creates, so a scout
    ships already labelled for the product surface it watches.

    Posture only shapes rows at creation (forward-only) — existing configs are never re-stamped,
    so flipping the flag later doesn't disturb teams already seeded, and a user enabling a scout
    won't be reverted on the next tick.

    The per-team `MAX_ENABLED_SCOUTS_PER_TEAM` cap is an independent second gate: even an
    allowlisted scout registers disabled once the team is at the cap. Both checks are best-effort
    (count + create, no lock) — a race can briefly overshoot by one, which the coordinator's
    per-tick caps still bound.

    A canonical scout declaring `scout-role: operational` (`lazy_seed.is_operational_scout`) is
    outside all of that: it watches the self-driving system rather than a product surface, so it
    seeds enabled, exempt from the inactivity sweep, past the allowlist and past the cap, and
    `reconcile_operational_configs` keeps rows seeded before the role existed on those terms. The
    holdback still applies — a withheld scout is dropped above, whatever its role.
    """
    enabled_skills, enabled_interval = _resolve_seed_posture(seed_config_layers)
    rows = list(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", "metadata")
    )
    skill_names = {name for name, _ in rows}
    # Drop held-back scouts up front: no config is seeded for them, and the returned set the
    # coordinator dispatches from never includes them. `sync_canonical_skills` already keeps
    # withheld skills from being seeded as `LLMSkill` rows, so this is mostly belt-and-suspenders
    # — it also covers a team that was previously allowed and still has the row.
    if withheld_skill_names:
        skill_names -= set(withheld_skill_names)
    # The allowlist governs the canonical fleet only; custom (hand-authored or duplicated) scouts
    # always auto-enable. A scout is canonical iff it BOTH carries the harness `seeded_by` tag AND
    # matches an on-disk canonical name — same dual check as `views._scout_origin`. The tag alone
    # isn't enough: `duplicate_skill` copies metadata verbatim, so a user's duplicate of a
    # canonical scout keeps the tag under a new, non-canonical name and must not be gated.
    on_disk_canonical = canonical_skill_names()
    canonical_names = {
        name
        for name, metadata in rows
        if (metadata or {}).get("seeded_by") == HARNESS_SEEDED_BY and name in on_disk_canonical
    }
    # Read off the canonical set, not the raw names: the role lives on disk, so a team's own scout
    # sharing an operational name must not inherit the posture that skips the harness's gates.
    operational_names = {name for name in canonical_names if is_operational_scout(name)}

    configs = SignalScoutConfig.objects.for_team(team_id)
    existing = set(configs.values_list("skill_name", flat=True))
    missing = sorted(skill_names - existing)
    enabled = enabled_scout_count(team_id) if missing else 0
    for name in missing:
        at_cap = enabled >= MAX_ENABLED_SCOUTS_PER_TEAM
        operational = name in operational_names
        # A canonical scout is gated by the allowlist (when one is set); a custom scout never is,
        # and neither is an operational one. The explicit `is not None` keeps the membership check
        # well-typed (mypy can't carry the narrowing through `gated`).
        gated = enabled_skills is not None and name in canonical_names and not operational
        in_allowlist = (not gated) or (enabled_skills is not None and name in enabled_skills)
        # The cap bounds what a team spends watching its own product, so an operational scout
        # seeds enabled past it. It still counts toward the cap, so its slot stays visible.
        seed_enabled = in_allowlist and (operational or not at_cap)

        defaults: dict = {} if seed_enabled else {"enabled": False}
        if operational:
            # The sweep reads the column, not the role, and writing memory hourly while filing a
            # report rarely is exactly the `no_output` shape it warns on.
            defaults["auto_pause_exempt"] = True
            defaults["auto_pause_exempt_by_role"] = True
        # A canonical scout can claim a product surface's tag in its SKILL.md frontmatter
        # (`scout-tags`) — that's what lands it in that product's own scout list. Seeded at
        # creation like the rest of the posture, so a person who later removes the tag keeps it
        # removed. Only canonical names read from disk: a team's scout sharing the name is its own.
        if name in canonical_names and (canonical_tags := canonical_config_tags_for(name)):
            defaults["tags"] = list(canonical_tags)
        # Likewise the write grant a canonical scout declares (`scout-write-scopes`): seeded once, so
        # a person who later narrows it in settings keeps it narrowed. Mint time intersects it
        # against the allowlist again, so a scope removed from the allowlist stops reaching runs.
        if name in canonical_names and (canonical_scopes := canonical_config_write_scopes_for(name)):
            defaults["write_scopes"] = list(canonical_scopes)
        # The launch cadence is stamped on every canonical (gated) scout — whether it seeds
        # enabled now or stays disabled for the user to switch on later — so a specialist a user
        # toggles on runs at the flag's launch cadence rather than the model default (daily).
        # Custom scouts keep the model default so a user's own scout isn't forced onto the
        # fleet's schedule.
        if gated and enabled_interval is not None:
            defaults["run_interval_minutes"] = enabled_interval

        # `team_id` must be passed as a kwarg: `get_or_create` builds the created row from
        # kwargs/defaults only — the queryset's team filter does not propagate into `create`.
        _, created = configs.get_or_create(team_id=team_id, skill_name=name, defaults=defaults)
        if not created:
            continue
        if seed_enabled:
            enabled += 1
        elif in_allowlist and at_cap:
            logger.info(
                "signals_scout: enabled-scout cap reached, auto-registered config disabled",
                team_id=team_id,
                skill_name=name,
                cap=MAX_ENABLED_SCOUTS_PER_TEAM,
            )

    reconcile_operational_configs(team_id, operational_names & skill_names, withheld_skill_names)

    # Keep the skills UI's Scouts tab in sync: stamp `category="scout"` on any scout skill rows
    # not yet categorized (custom scouts authored via the skills API). Runs every reconcile tick,
    # and after the loop above so a row created on this tick is stamped on this tick.
    ensure_scout_category(team_id)
    return skill_names | live_scout_skill_names(team_id, withheld_skill_names)


@transaction.atomic
def reconcile_operational_configs(
    team_id: int,
    skill_names: set[str],
    withheld_skill_names: frozenset[str] | set[str] | None = None,
) -> None:
    """Put already-seeded operational scouts back on the posture their role asks for.

    The rest of the seed posture is forward-only on purpose: an existing row is the team's to
    tune, and re-stamping it every tick would revert people's choices. An operational scout is
    the exception because it watches the self-driving system itself — when it is off, the thing
    that notices nothing is working is the thing that stopped working — so the harness's own
    earlier decisions about it are undone rather than left standing.

    Two of them. The exemption is stamped whenever it is missing, so the inactivity sweep stops
    reading the scout's designed quiet as waste. And a scout the harness silenced is resumed: a
    sweep warning or pause through `transition_status_by_system` under the sweep's own reason,
    and a row the seed created disabled (recognized by a `paused_by_user` status no writer has
    moved since creation) by a direct write, since the lifecycle rightly refuses to overrule a
    human pause and that is what an untouched seed row is stored as.

    What it never touches: a pause a person made, and a pause the failure breaker owns. A scout
    whose runs keep failing has its own half-open probe, and resuming it here would spend runs on
    a scout that cannot finish one.
    """
    configs = (
        SignalScoutConfig.objects.for_team(team_id)
        .select_for_update()
        .filter(Q(skill_name__in=skill_names) | Q(auto_pause_exempt_by_role=True))
        .exclude(skill_name__in=withheld_skill_names or ())
    )
    for config in configs:
        trigger = Trigger(
            job_type=_OPERATIONAL_RECONCILE_JOB_TYPE,
            job_id=str(config.id),
            payload={"skill_name": config.skill_name},
        )
        with ActivityTriggerContext(trigger):
            if config.skill_name not in skill_names:
                config.auto_pause_exempt = False
                config.auto_pause_exempt_by_role = False
                config.save(update_fields=["auto_pause_exempt", "auto_pause_exempt_by_role", "updated_at"])
                continue
            if not config.auto_pause_exempt:
                config.auto_pause_exempt = True
                config.auto_pause_exempt_by_role = True
                config.save(update_fields=["auto_pause_exempt", "auto_pause_exempt_by_role", "updated_at"])
                logger.info(
                    "signals_scout: operational scout exempted from the inactivity sweep",
                    team_id=team_id,
                    skill_name=config.skill_name,
                )
            _resume_operational_config(config)


def _resume_operational_config(config: SignalScoutConfig) -> None:
    """Undo the harness's own silencing of one operational scout, and nothing else."""
    if config.pause_reason in SignalScoutConfig.INACTIVITY_PAUSE_REASONS:
        resumed = config.transition_status_by_system(
            SignalScoutConfig.Status.ACTIVE,
            pause_reason=SignalScoutConfig.PauseReason(config.pause_reason),
        )
    elif config.status == SignalScoutConfig.Status.PAUSED_BY_USER and config.status_changed_at is None:
        # `save` stores an `enabled=False` create as `paused_by_user`, so a row the seed disabled
        # is shaped like a human pause. The missing `status_changed_at` is what tells them apart:
        # it is stamped on every transition, and null only while the row still sits as created.
        config.status = SignalScoutConfig.Status.ACTIVE
        config.enabled = True
        config.pause_reason = None
        config.save(update_fields=["status", "enabled", "pause_reason", "updated_at"])
        resumed = True
    else:
        return
    if resumed:
        logger.info(
            "signals_scout: operational scout resumed",
            team_id=config.team_id,
            skill_name=config.skill_name,
        )
