"""Whether a scout config is an operational scout.

A config is operational when its skill is the live row the harness seeded for a canonical scout
that declares `scout-role: operational`. The name alone proves nothing. A team can author its own
skill under an operational scout's name before the harness seeds that scout, and the sync then
leaves the team's row alone. That skill inherits nothing from disk.

`seeded_by` is a harness-owned metadata key that the skills API never accepts from a caller, so
it proves who wrote the row. Use these helpers for any check on a config, not the name-only
`lazy_seed.is_operational_scout`.

Two checks, for two kinds of exemption:

- `operational_config_q` decides how the harness maintains a scout: reconcile, setup pauses, and
  which scouts count as a person's choice. It is a SQL filter, so it reads the seeded tag only.
- `unedited_operational_skill_names` decides what a team does not pay for. A team that edits an
  operational scout owns the result, so it counts like a custom scout. This matches run billing
  (`spend_billing.scout_skill_spend_exempt`), which makes the same content hash comparison.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from products.signals.backend.scout_harness.lazy_seed import (
    HARNESS_SEEDED_BY,
    canonical_operational_scout_names,
    scout_skill_row_is_proven_canonical,
)
from products.skills.backend.models.skills import LLMSkill


def harness_seeded_skill_exists() -> Exists:
    """Whether the config's skill is the live, harness-seeded canonical row, not a team's own copy."""
    return Exists(
        LLMSkill.objects.filter(
            team_id=OuterRef("team_id"),
            name=OuterRef("skill_name"),
            is_latest=True,
            deleted=False,
            metadata__seeded_by=HARNESS_SEEDED_BY,
        )
    )


def operational_config_q() -> Q:
    """Filter for `SignalScoutConfig` rows that are operational scouts."""
    return Q(skill_name__in=canonical_operational_scout_names()) & Q(harness_seeded_skill_exists())


def unedited_operational_skill_names(team_id: int) -> frozenset[str]:
    """The team's operational scouts whose skill still holds the content PostHog shipped.

    `team_id` must be the parent project, because scout skills live there. A seeded row with no
    `canonical_hash` is excluded, because nothing proves it is unedited.
    """
    names = canonical_operational_scout_names()
    if not names:
        return frozenset()
    skills = LLMSkill.objects.filter(
        team_id=team_id, name__in=names, is_latest=True, deleted=False, metadata__seeded_by=HARNESS_SEEDED_BY
    ).prefetch_related("files")
    return frozenset(skill.name for skill in skills if scout_skill_row_is_proven_canonical(skill))
