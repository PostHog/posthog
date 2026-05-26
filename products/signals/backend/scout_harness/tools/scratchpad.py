"""Durable memory tools: read/write `SignalScratchpad` entries for the team.

The scout calls `remember`/`forget` via this module. Scratchpad is the narrow
per-team memory surface — MCP-readable across agents — that other scouts and
PostHog AI can read to see what the scout fleet has learned about a team.

Simplified in PR 2 review: `tags`, `scope`, `expires_at`, and `authority` were
dropped (none were earning their keep on the stack). Retrieval is ILIKE on
`content` and `key` only; all entries are durable per-team memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from django.db import IntegrityError, transaction

from products.signals.backend.models import SignalScratchpad

# Defensive cap on search results.
DEFAULT_SCRATCHPAD_SEARCH_LIMIT = 20
MAX_SCRATCHPAD_SEARCH_LIMIT = 100

# Keys/content are agent-chosen prose. Match the model's column lengths so callers
# get a clean error before hitting the DB.
MAX_SCRATCHPAD_KEY_LENGTH = 300


class InvalidScratchpadError(ValueError):
    """The agent tried to write a memory with invalid shape (empty key, oversized, etc)."""


@dataclass(frozen=True)
class ScratchpadEntry:
    key: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None
    created_by_run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_scratchpad(
    *,
    team_id: int,
    text: str | None = None,
    limit: int = DEFAULT_SCRATCHPAD_SEARCH_LIMIT,
) -> list[ScratchpadEntry]:
    """Return memories the agent should consider when planning a run.

    `text` matches ILIKE against `content` and `key`. The previous `tags` filter
    + GIN index were dropped in PR 2 review.
    """
    clamped_limit = _clamp_search_limit(limit)
    qs = SignalScratchpad.objects.filter(team_id=team_id)
    if text:
        from django.db.models import Q

        qs = qs.filter(Q(content__icontains=text) | Q(key__icontains=text))
    qs = qs.order_by("-updated_at", "-id")[:clamped_limit]
    return [_to_entry(row) for row in qs]


def remember(
    *,
    team_id: int,
    key: str,
    content: str,
    run_id: str | None = None,
) -> ScratchpadEntry:
    """Write or update a memory entry. Idempotent on `(team, key)`.

    The previous `human_confirmed` authority guard was dropped — the human-in-the-
    loop write path was reserved-for-future and never landed. Re-add if it ships.
    """
    _validate_key_content(key, content)

    try:
        row = _upsert_entry(team_id=team_id, key=key, content=content, run_id=run_id)
    except IntegrityError:
        # Lost the create race: our SELECT saw no row, but a concurrent request
        # committed an insert for the same `(team, key)` before ours, tripping the
        # unique constraint. The row now exists, so a single retry resolves to the
        # update branch and preserves the idempotent-upsert contract.
        row = _upsert_entry(team_id=team_id, key=key, content=content, run_id=run_id)
    return _to_entry(row)


def _upsert_entry(*, team_id: int, key: str, content: str, run_id: str | None) -> SignalScratchpad:
    with transaction.atomic():
        existing = SignalScratchpad.objects.select_for_update().filter(team_id=team_id, key=key).first()
        if existing is None:
            return SignalScratchpad.objects.create(
                team_id=team_id,
                key=key,
                content=content,
                created_by_run_id=run_id,
            )
        existing.content = content
        # Don't overwrite `created_by_run` so we keep the original creator's lineage.
        existing.save(update_fields=["content", "updated_at"])
        return existing


def forget(*, team_id: int, key: str) -> bool:
    """Delete an entry by key. Returns whether anything was removed (False = no-op)."""
    with transaction.atomic():
        existing = SignalScratchpad.objects.select_for_update().filter(team_id=team_id, key=key).first()
        if existing is None:
            return False
        existing.delete()
    return True


def _validate_key_content(key: str, content: str) -> None:
    if not key or not key.strip():
        raise InvalidScratchpadError("memory key must be non-empty")
    if len(key) > MAX_SCRATCHPAD_KEY_LENGTH:
        raise InvalidScratchpadError(f"memory key length {len(key)} exceeds max {MAX_SCRATCHPAD_KEY_LENGTH}")
    if not content or not content.strip():
        raise InvalidScratchpadError("memory content must be non-empty")


def _clamp_search_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_SCRATCHPAD_SEARCH_LIMIT:
        return MAX_SCRATCHPAD_SEARCH_LIMIT
    return limit


def _to_entry(row: SignalScratchpad) -> ScratchpadEntry:
    # Django's FK descriptor exposes both `created_by_run` (object) and `created_by_run_id`
    # (the raw FK column). `getattr` keeps Pyright happy without a join.
    run_pk = getattr(row, "created_by_run_id", None)
    return ScratchpadEntry(
        key=row.key,
        content=row.content,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        created_by_run_id=str(run_pk) if run_pk else None,
    )
