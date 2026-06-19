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
from products.signals.backend.scout_harness.lazy_seed import SCOUT_SKILL_CATEGORY
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)


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


def register_missing_configs(team_id: int) -> set[str]:
    """Auto-create a default-schedule config for each scout skill lacking a row.

    Idempotent — `get_or_create` keyed on the `(team, skill_name)` unique constraint, so
    concurrent callers (coordinator tick racing an API call) converge on one row. Returns
    the set of live `signals-scout-*` skill names for the team, so the caller can skip
    dispatching configs whose skill is gone.

    New rows default to enabled until the team hits `MAX_ENABLED_SCOUTS_PER_TEAM`; past
    the cap they register disabled, so the scout is still visible and tunable but never
    silently adds spend. The check is best-effort (count + create, no lock) — a race can
    briefly overshoot by one, which the coordinator's per-tick caps still bound.
    """
    skill_names = set(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    # Keep the skills UI's Scouts tab in sync: stamp `category="scout"` on any scout skill rows
    # not yet categorized (custom scouts authored via the skills API). Runs every reconcile tick.
    ensure_scout_category(team_id)
    configs = SignalScoutConfig.objects.for_team(team_id)
    existing = set(configs.values_list("skill_name", flat=True))
    missing = sorted(skill_names - existing)
    if not missing:
        return skill_names

    enabled = enabled_scout_count(team_id)
    for name in missing:
        at_cap = enabled >= MAX_ENABLED_SCOUTS_PER_TEAM
        # `team_id` must be passed as a kwarg: `get_or_create` builds the created row from
        # kwargs/defaults only — the queryset's team filter does not propagate into `create`.
        _, created = configs.get_or_create(
            team_id=team_id,
            skill_name=name,
            defaults={"enabled": False} if at_cap else {},
        )
        if created and at_cap:
            logger.info(
                "signals_scout: enabled-scout cap reached, auto-registered config disabled",
                team_id=team_id,
                skill_name=name,
                cap=MAX_ENABLED_SCOUTS_PER_TEAM,
            )
        elif created:
            enabled += 1
    return skill_names
