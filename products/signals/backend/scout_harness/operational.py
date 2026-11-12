"""Whether a scout config is an operational scout.

A config is operational when its skill is the live row the harness seeded for a canonical scout
that declares `scout-role: operational`. The name alone proves nothing. A team can author its own
skill under an operational scout's name before the harness seeds that scout, and the sync then
leaves the team's row alone. That skill inherits nothing from disk, so it gets none of the
exemptions the role grants, such as running outside the free trial's scout slots.

`seeded_by` is a harness-owned metadata key that the skills API never accepts from a caller, so
it proves who wrote the row. Use these helpers for any check on a config, not the name-only
`lazy_seed.is_operational_scout`.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q, QuerySet

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import (
    HARNESS_SEEDED_BY,
    canonical_operational_scout_names,
    is_operational_scout,
)
from products.skills.backend.models.skills import LLMSkill


def _harness_seeded_skills(team_id: int | OuterRef, skill_name: str | OuterRef) -> QuerySet[LLMSkill]:
    return LLMSkill.objects.filter(
        team_id=team_id,
        name=skill_name,
        is_latest=True,
        deleted=False,
        metadata__seeded_by=HARNESS_SEEDED_BY,
    )


def harness_seeded_skill_exists() -> Exists:
    """Whether the config's skill is the live, harness-seeded canonical row, not a team's own copy."""
    return Exists(_harness_seeded_skills(OuterRef("team_id"), OuterRef("skill_name")))


def operational_config_q() -> Q:
    """Filter for `SignalScoutConfig` rows that are operational scouts."""
    return Q(skill_name__in=canonical_operational_scout_names()) & Q(harness_seeded_skill_exists())


def is_operational_config(config: SignalScoutConfig) -> bool:
    if not is_operational_scout(config.skill_name):
        return False
    # An unsaved config can still point at a child environment, because the model moves it to the
    # parent project only inside `save()`. Scout skills live on the parent project.
    team_id = config.team.parent_team_id or config.team_id
    return _harness_seeded_skills(team_id, config.skill_name).exists()
