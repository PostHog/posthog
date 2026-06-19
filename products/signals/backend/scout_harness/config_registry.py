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
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

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


def _resolve_seed_posture(seed_config: dict | None) -> tuple[set[str] | None, int | None]:
    """Parse the optional seed posture from a resolved per-team config blob.

    Returns `(enabled_skills, enabled_interval_minutes)`:
    - `enabled_skills`: the allowlist of canonical scouts that auto-enable on seed; everything
      else registers disabled. `None` means "no allowlist" — every scout enables, the historical
      behaviour.
    - `enabled_interval_minutes`: cadence stamped on the auto-enabled rows, or `None` to keep the
      model default.

    The blob is arbitrary flag JSON, so both keys are validated; a malformed value is treated as
    absent (falls back to historical behaviour) rather than failing the seed.
    """
    if not seed_config:
        return None, None

    enabled_skills: set[str] | None = None
    raw_skills = seed_config.get("enabled_skills")
    if isinstance(raw_skills, list) and all(isinstance(s, str) for s in raw_skills):
        enabled_skills = {str(s) for s in raw_skills}

    enabled_interval: int | None = None
    raw_interval = seed_config.get("enabled_interval_minutes")
    if isinstance(raw_interval, int) and not isinstance(raw_interval, bool) and raw_interval > 0:
        enabled_interval = raw_interval

    return enabled_skills, enabled_interval


def register_missing_configs(team_id: int, seed_config: dict | None = None) -> set[str]:
    """Auto-create a config for each scout skill lacking a row, honouring an optional seed posture.

    Idempotent — `get_or_create` keyed on the `(team, skill_name)` unique constraint, so
    concurrent callers (coordinator tick racing an API call) converge on one row. Returns
    the set of live `signals-scout-*` skill names for the team, so the caller can skip
    dispatching configs whose skill is gone.

    `seed_config` is the team's resolved flag config (`default_team_config` merged with its
    `team_configs` override). When it carries an `enabled_skills` allowlist, only those scouts
    auto-enable (at `enabled_interval_minutes` if set) and the rest register disabled — the
    launch posture (e.g. general-only, once a day). With no allowlist the historical behaviour
    holds: every scout enables at the model-default schedule. Either way, a scout disabled at seed
    stays visible and tunable but adds no spend.

    Posture only shapes rows at creation (forward-only) — existing configs are never re-stamped,
    so flipping the flag later doesn't disturb teams already seeded, and a user enabling a scout
    won't be reverted on the next tick.

    The per-team `MAX_ENABLED_SCOUTS_PER_TEAM` cap is an independent second gate: even an
    allowlisted scout registers disabled once the team is at the cap. Both checks are best-effort
    (count + create, no lock) — a race can briefly overshoot by one, which the coordinator's
    per-tick caps still bound.
    """
    enabled_skills, enabled_interval = _resolve_seed_posture(seed_config)
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
        in_allowlist = enabled_skills is None or name in enabled_skills
        seed_enabled = in_allowlist and not at_cap

        defaults: dict = {} if seed_enabled else {"enabled": False}
        if seed_enabled and enabled_interval is not None:
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
