"""Auto-registration of `SignalScoutConfig` rows for `signals-scout-*` skills.

The "author a skill, get a scout" contract: any `signals-scout-*` `LLMSkill` on a team
gets a `SignalScoutConfig` row (default schedule, enabled) with no further wiring. The
Temporal coordinator tick calls this so enrolled teams reconcile on schedule. The HTTP
surface deliberately does not: reads stay side-effect free, and explicit registration
goes through the write-scoped config `create` endpoint.
"""

from __future__ import annotations

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX


def register_missing_configs(team_id: int) -> set[str]:
    """Auto-create an enabled, default-schedule config for each scout skill lacking a row.

    Idempotent — `get_or_create` keyed on the `(team, skill_name)` unique constraint, so
    concurrent callers (coordinator tick racing an API call) converge on one row. Returns
    the set of live `signals-scout-*` skill names for the team, so the caller can skip
    dispatching configs whose skill is gone.
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
    for name in sorted(skill_names - existing):
        # `team_id` must be passed as a kwarg: `get_or_create` builds the created row from
        # kwargs/defaults only — the queryset's team filter does not propagate into `create`.
        configs.get_or_create(team_id=team_id, skill_name=name)
    return skill_names
