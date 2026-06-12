"""Auto-registration of `SignalScoutConfig` rows for `signals-scout-*` skills.

The "author a skill, get a scout" contract: any `signals-scout-*` `LLMSkill` on a team
gets a `SignalScoutConfig` row (default schedule, enabled) with no further wiring. The
Temporal coordinator tick calls this so enrolled teams reconcile on schedule. The HTTP
surface deliberately does not: reads stay side-effect free, and explicit registration
goes through the write-scoped config `create` endpoint.
"""

from __future__ import annotations

import structlog

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX

logger = structlog.get_logger(__name__)


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
