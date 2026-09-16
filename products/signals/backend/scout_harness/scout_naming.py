"""Turning a scout's display name into the stable slug that identifies it.

A scout carries two names. `SignalScoutConfig.display_name` is what a person typed and what
every surface renders; the skill name is the slug, and it is the identity: run history, notes,
scratchpad memory, report attribution, and deep links are all keyed on it. So the slug is
generated once, at creation, and never moves again — renaming a scout only rewrites the
display name.

Generation lives here rather than in the serializer because the create path has to retry it:
the slug is chosen by reading the names already taken, and a concurrent create can take the
chosen one between the read and the insert.
"""

from __future__ import annotations

import re
import unicodedata
from secrets import token_hex

from django.utils.text import slugify

from products.signals.backend.models import SignalScoutConfig
from products.skills.backend.api.skill_services import MAX_SKILL_NAME_LENGTH
from products.skills.backend.models.skills import LLMSkill

# The slug has to satisfy `validate_skill_name_value`, which allows lowercase letters, digits and
# single interior hyphens only. Underscores survive Django's `slugify`, so they are folded to
# hyphens before it runs rather than stripped after, which would join the words either side.
_UNDERSCORES = re.compile(r"_+")
_HYPHEN_RUNS = re.compile(r"-{2,}")

# Tried in order before falling back to a random slug. A team holds a couple of dozen scouts, so
# a name colliding ten deep means something other than ordinary duplicate naming.
_MAX_COLLISION_SUFFIX = 10

# Stem for the fallback slug, used when a display name survives slugification with nothing left
# (all punctuation, or a script `slugify` transliterates away) or when the suffix search is
# exhausted. The hex tail makes it unique on its own, so it needs no collision pass.
_FALLBACK_SLUG_PREFIX = "scout"


def slugify_scout_name(display_name: str) -> str:
    """The slug a display name reduces to, or `""` when nothing usable survives.

    Callers decide what empty means; both current ones fall back to `fallback_scout_slug`, so a
    name written in a script that does not transliterate still produces a usable scout.
    """
    folded = _UNDERSCORES.sub("-", unicodedata.normalize("NFKD", display_name))
    slug = _HYPHEN_RUNS.sub("-", slugify(folded)).strip("-")
    return _truncate_slug(slug, MAX_SKILL_NAME_LENGTH)


def fallback_scout_slug() -> str:
    """A valid slug for a display name that reduces to nothing."""
    return f"{_FALLBACK_SLUG_PREFIX}-{token_hex(4)}"


def allocate_scout_slug(*, team_id: int, display_name: str, taken: set[str] | None = None) -> str:
    """A slug for `display_name` that no scout on this team holds yet.

    Duplicate display names are allowed, so the collision pass is the normal path, not an error
    case: a second "Checkout failures" becomes `checkout-failures-2`. Both name spaces are
    checked, because a scout needs a free skill name and a free config row under it.

    `taken` adds names this caller has already tried and lost — the create path passes the slugs
    a concurrent create won from under it, so a retry does not re-pick one of them.

    Best-effort, like every read-then-insert: the caller still has to handle losing the race.
    """
    base = slugify_scout_name(display_name)
    if not base:
        return fallback_scout_slug()
    reserved = set(taken or ())
    reserved |= set(
        LLMSkill.objects.filter(team_id=team_id, deleted=False, name__startswith=base).values_list("name", flat=True)
    )
    reserved |= set(
        SignalScoutConfig.objects.for_team(team_id)
        .filter(skill_name__startswith=base)
        .values_list("skill_name", flat=True)
    )
    if base not in reserved:
        return base
    for suffix in range(2, _MAX_COLLISION_SUFFIX + 1):
        tail = f"-{suffix}"
        candidate = f"{_truncate_slug(base, MAX_SKILL_NAME_LENGTH - len(tail))}{tail}"
        if candidate not in reserved:
            return candidate
    return fallback_scout_slug()


def _truncate_slug(slug: str, limit: int) -> str:
    """`slug` cut to `limit` characters, without leaving the trailing hyphen the cut can expose."""
    return slug[:limit].rstrip("-")
