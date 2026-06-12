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

    A skill may declare its own default cadence via frontmatter
    `metadata.default-run-interval-minutes` (persisted by the canonical seed as
    `metadata.default_run_interval_minutes` on the row). It applies only at config
    creation — operator retuning of an existing row is never overwritten.
    """
    rows = LLMSkill.objects.filter(
        team_id=team_id,
        name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
        is_latest=True,
        deleted=False,
    ).values_list("name", "metadata")
    skill_names = {name for name, _ in rows}
    default_intervals: dict[str, int] = {}
    for name, metadata in rows:
        interval = (metadata or {}).get("default_run_interval_minutes")
        # Bounds mirror SignalScoutConfig.run_interval_minutes validators. An out-of-range or
        # non-int value (e.g. a hand-edited row) falls back to the model default instead of
        # erroring the coordinator tick.
        if isinstance(interval, int) and not isinstance(interval, bool) and 10 <= interval <= 43200:
            default_intervals[name] = interval
    configs = SignalScoutConfig.objects.for_team(team_id)
    existing = set(configs.values_list("skill_name", flat=True))
    for name in sorted(skill_names - existing):
        defaults = {"run_interval_minutes": default_intervals[name]} if name in default_intervals else {}
        # `team_id` must be passed as a kwarg: `get_or_create` builds the created row from
        # kwargs/defaults only — the queryset's team filter does not propagate into `create`.
        configs.get_or_create(team_id=team_id, skill_name=name, defaults=defaults)
    return skill_names
