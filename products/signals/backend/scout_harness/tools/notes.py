"""Scout notes: steering notes humans (or other agents) leave for the fleet.

The inbound counterpart to `scratchpad.py` — the scratchpad is what the fleet
learned (agent-authored, sandbox-write-only), a note is what the team wants the
fleet to know (authored over the public MCP surface via `signal_scout:write`).
A note targets one scout by `skill_name`, or the whole fleet when `skill_name`
is blank; `list_notes` is what a run calls to pick up the notes addressed to it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from products.signals.backend.models import SignalScoutNote
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.skills.backend.models.skills import LLMSkill

# Defensive caps on the list surface. The default is sized for the scout cold-start read —
# the newest handful of steering notes — not for archival browsing; callers page for more.
DEFAULT_NOTES_LIST_LIMIT = 20
MAX_NOTES_LIST_LIMIT = 500

# `content` is read verbatim into a run's context — cap it so one note can't dominate a
# prompt. Deliberately tighter than the scratchpad cap: notes are pointers, not documents.
MAX_NOTE_CONTENT_LENGTH = 10_000


class InvalidNoteError(ValueError):
    """The caller tried to leave a note with invalid shape (empty content, bad target)."""


@dataclass(frozen=True)
class ScoutNote:
    id: str
    skill_name: str
    content: str
    created_at: str | None = None
    expires_at: str | None = None
    # Display name only — author emails stay behind the internal-scope member roster.
    created_by_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_notes(
    *,
    team_id: int,
    skill_name: str | None = None,
    include_general: bool = True,
    include_expired: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = DEFAULT_NOTES_LIST_LIMIT,
    content_max_chars: int | None = None,
) -> list[ScoutNote]:
    """Return notes for a team, newest first.

    `skill_name=None` returns every note (the browse view). A concrete `skill_name`
    returns that scout's notes plus — unless `include_general=False` — the general
    (blank-target) notes addressed to the whole fleet; this is the shape a scout run
    calls with at cold start.

    Expired notes (`expires_at` in the past) are excluded by default so time-boxed
    steering retires itself; `include_expired=True` brings them back for humans
    auditing the history. `date_from` / `date_to` are a half-open window on
    `created_at` (`>= date_from`, `< date_to`) for walking past the cap.

    `content_max_chars` truncates each `content` to a preview — a wide scan's guard
    against notes stacking up to `MAX_NOTE_CONTENT_LENGTH × limit` characters of
    prose (a plain Python slice; note volume is small, unlike the scratchpad's
    SQL-projected equivalent).
    """
    clamped_limit = min(max(limit, 1), MAX_NOTES_LIST_LIMIT)
    qs = SignalScoutNote.objects.filter(team_id=team_id).select_related("created_by")
    if skill_name is not None:
        target = Q(skill_name=skill_name)
        if include_general:
            target |= Q(skill_name="")
        qs = qs.filter(target)
    if not include_expired:
        qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    if date_from is not None:
        qs = qs.filter(created_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(created_at__lt=date_to)
    qs = qs.order_by("-created_at", "-id")[:clamped_limit]
    return [_to_note(row, content_max_chars=content_max_chars) for row in qs]


def leave_note(
    *,
    team_id: int,
    content: str,
    skill_name: str = "",
    created_by_id: int | None = None,
    expires_at: datetime | None = None,
) -> ScoutNote:
    """Create a note. Not an upsert — every call mints a new row; delete retires one."""
    _validate_note(team_id=team_id, skill_name=skill_name, content=content)
    row = SignalScoutNote.objects.create(
        team_id=team_id,
        skill_name=skill_name,
        content=content,
        created_by_id=created_by_id,
        expires_at=expires_at,
    )
    return _to_note(row)


def delete_note(*, team_id: int, note_id: str) -> bool:
    """Delete a note by id. Returns whether anything was removed (False = no-op)."""
    with transaction.atomic():
        existing = SignalScoutNote.objects.select_for_update().filter(team_id=team_id, id=note_id).first()
        if existing is None:
            return False
        existing.delete()
    return True


def _validate_note(*, team_id: int, skill_name: str, content: str) -> None:
    if not content or not content.strip():
        raise InvalidNoteError("note content must be non-empty")
    if len(content) > MAX_NOTE_CONTENT_LENGTH:
        raise InvalidNoteError(f"note content length {len(content)} exceeds max {MAX_NOTE_CONTENT_LENGTH}")
    # A typo'd target silently steers no one — the list filter is an exact match — so a targeted
    # note must name a scout skill that actually exists on this project. Blank stays valid: it
    # addresses the whole fleet.
    if not skill_name:
        return
    if not skill_name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
        raise InvalidNoteError(
            f"skill_name must be blank (a note for every scout) or start with '{SIGNALS_SCOUT_SKILL_PREFIX}'"
        )
    if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, deleted=False).exists():
        raise InvalidNoteError(
            f"no scout skill named '{skill_name}' exists on this project — check `scout-config-list` "
            "for the roster, or author the skill first"
        )


def _to_note(row: SignalScoutNote, *, content_max_chars: int | None = None) -> ScoutNote:
    user = row.created_by
    name = f"{user.first_name} {user.last_name}".strip() if user is not None else None
    content = row.content if content_max_chars is None else row.content[: max(content_max_chars, 0)]
    return ScoutNote(
        id=str(row.id),
        skill_name=row.skill_name,
        content=content,
        created_at=row.created_at.isoformat() if row.created_at else None,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_by_name=name or None,
    )
