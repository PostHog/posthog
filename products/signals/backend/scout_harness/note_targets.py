"""Who a scout note can be addressed to, and the rule that checks it.

Kept apart from `tools/notes.py` on purpose. Importing anything under `tools/` runs that package's
`__init__`, which pulls in every harness tool, and the Django admin form needs this rule at
registry load. This module reaches only the skills model and the scout skill prefix.
"""

from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

# Audiences that are a stage of the report pipeline rather than a scout. A stage is not an
# `LLMSkill` row, so it cannot be named the way a scout is, but its notes want the same shape:
# addressed to one reader, plus whatever the whole fleet was told. The pseudo-target therefore
# rides the existing `skill_name` column under a `pipeline:` prefix that no scout name can
# collide with (scouts are `signals-scout-*`), which needs no column and no migration. The read
# side needs no change either: `list_notes` matches `skill_name` exactly, so a stage sees its own
# notes plus the blank-target ones, and a scout never sees a pipeline note.
PIPELINE_AUDIENCE_PREFIX = "pipeline:"
PIPELINE_AUDIENCE_REPORT_RESEARCH = f"{PIPELINE_AUDIENCE_PREFIX}report-research"
PIPELINE_AUDIENCE_IMPLEMENTATION = f"{PIPELINE_AUDIENCE_PREFIX}implementation"
# Allowlisted, not free-form: an unrecognized `pipeline:*` target steers no one, which is the same
# silent failure a typo'd scout name would cause. Add a stage here when it starts reading notes.
# The implementation stage is deliberately absent: it takes its steering from the task
# description `report_steering.load_report_steering` builds, so a note left for it would sit unread.
PIPELINE_AUDIENCES: frozenset[str] = frozenset({PIPELINE_AUDIENCE_REPORT_RESEARCH})

# The same strings in their other role — what a pipeline stage stamps on a scratchpad entry it
# writes, so a search result attributes the entry the way a scout's run FK does. Kept as its own
# set because reading notes and writing memory are separate capabilities: a stage can remember
# what it learned without being addressable.
PIPELINE_WRITER_IDENTITIES: frozenset[str] = frozenset(
    {
        PIPELINE_AUDIENCE_REPORT_RESEARCH,
        PIPELINE_AUDIENCE_IMPLEMENTATION,
    }
)


class InvalidNoteError(ValueError):
    """The caller tried to leave a note with invalid shape (empty content, bad target)."""


def validate_note_target(*, team_id: int, skill_name: str) -> None:
    """Raise `InvalidNoteError` unless `skill_name` names an audience a note can reach.

    Shared with the Django admin form so both write paths accept the same set of targets.
    """
    # A typo'd target silently steers no one — the list filter is an exact match — so a targeted
    # note must name a reader that exists. Blank stays valid: it addresses the whole fleet.
    if not skill_name:
        return
    if skill_name.startswith(PIPELINE_AUDIENCE_PREFIX):
        if skill_name not in PIPELINE_AUDIENCES:
            raise InvalidNoteError(
                f"'{skill_name}' is not a pipeline audience — the reserved ones are "
                f"{', '.join(sorted(PIPELINE_AUDIENCES))}"
            )
        return
    if not skill_name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
        raise InvalidNoteError(
            f"skill_name must be blank (a note for every scout), a scout skill name starting with "
            f"'{SIGNALS_SCOUT_SKILL_PREFIX}', or a pipeline audience "
            f"({', '.join(sorted(PIPELINE_AUDIENCES))})"
        )
    if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, deleted=False).exists():
        raise InvalidNoteError(
            f"no scout skill named '{skill_name}' exists on this project — check `scout-config-list` "
            "for the roster, or author the skill first"
        )
