"""Auto-registration of `SignalScoutConfig` rows for `signals-scout-*` skills.

The "author a skill, get a scout" contract: any `signals-scout-*` `LLMSkill` on a team
gets a `SignalScoutConfig` row (default schedule, enabled) with no further wiring. The
Temporal coordinator tick calls this so enrolled teams reconcile on schedule. The HTTP
surface deliberately does not: reads stay side-effect free, and explicit registration
goes through the write-scoped config `create` endpoint.
"""

from __future__ import annotations

import structlog

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import (
    HARNESS_SEEDED_BY,
    SCOUT_SKILL_CATEGORY,
    canonical_skill_names,
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


def ensure_scout_category(team_id: int, skill_name: str | None = None) -> None:
    """Stamp `LLMSkill.category="scout"` on the team's scout skill rows.

    `category` is server-owned, so this is how custom scouts authored via the normal skills API
    get categorized — canonical scouts are already stamped at seed time (`lazy_seed`). Without it
    a freshly authored `signals-scout-*` skill would schedule but stay off the skills UI's Scouts
    tab. Idempotent (skips already-stamped rows). Pass `skill_name` to stamp one scout (e.g. on
    explicit registration), or omit to reconcile every `signals-scout-*` row for the team.
    """
    rows = LLMSkill.objects.filter(team_id=team_id, deleted=False).exclude(category=SCOUT_SKILL_CATEGORY)
    if skill_name is not None:
        rows = rows.filter(name=skill_name)
    else:
        rows = rows.filter(name__startswith=SIGNALS_SCOUT_SKILL_PREFIX)
    rows.update(category=SCOUT_SKILL_CATEGORY)


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
    """Live (latest, non-deleted) `signals-scout-*` skill names for a team, minus the holdback set.

    The read-only half of `register_missing_configs`'s skill scan, with no seeding side effects. The
    coordinator dispatches only configs whose skill is in this set, so a config whose skill was
    deleted or superseded isn't run. Used on the wildcard (no-seed) dispatch path — a team that
    self-enrolled through the UI already has its configs, so the per-tick seed/reconcile is skipped
    and this cheap read is what still gates dispatch correctly.
    """
    names = set(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    if withheld_skill_names:
        names -= set(withheld_skill_names)
    return names


def register_missing_configs(
    team_id: int,
    seed_config_layers: list[dict] | None = None,
    withheld_skill_names: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Auto-create a config for each scout skill lacking a row, honouring an optional seed posture.

    Idempotent — `get_or_create` keyed on the `(team, skill_name)` unique constraint, so
    concurrent callers (coordinator tick racing an API call) converge on one row. Returns
    the set of live `signals-scout-*` skill names for the team, so the caller can skip
    dispatching configs whose skill is gone.

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

    Posture only shapes rows at creation (forward-only) — existing configs are never re-stamped,
    so flipping the flag later doesn't disturb teams already seeded, and a user enabling a scout
    won't be reverted on the next tick.

    The per-team `MAX_ENABLED_SCOUTS_PER_TEAM` cap is an independent second gate: even an
    allowlisted scout registers disabled once the team is at the cap. Both checks are best-effort
    (count + create, no lock) — a race can briefly overshoot by one, which the coordinator's
    per-tick caps still bound.
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
    # Keep the skills UI's Scouts tab in sync: stamp `category="scout"` on any scout skill rows
    # not yet categorized (custom scouts authored via the skills API). Runs every reconcile tick.
    ensure_scout_category(team_id)
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

    configs = SignalScoutConfig.objects.for_team(team_id)
    existing = set(configs.values_list("skill_name", flat=True))
    missing = sorted(skill_names - existing)
    if not missing:
        return skill_names

    enabled = enabled_scout_count(team_id)
    for name in missing:
        at_cap = enabled >= MAX_ENABLED_SCOUTS_PER_TEAM
        # A canonical scout is gated by the allowlist (when one is set); a custom scout never is.
        # The explicit `is not None` keeps the membership check well-typed (mypy can't carry the
        # narrowing through `gated`).
        gated = enabled_skills is not None and name in canonical_names
        in_allowlist = (not gated) or (enabled_skills is not None and name in enabled_skills)
        seed_enabled = in_allowlist and not at_cap

        defaults: dict = {} if seed_enabled else {"enabled": False}
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
    return skill_names
