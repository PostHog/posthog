"""Durable memory tools: read/write `SignalMemory` entries for the team.

The agent calls `remember`/`forget` via this module. All agent-written entries
have authority `agent_inference` and are TTL'd. The schema reserves a
`human_confirmed` authority class for a future human-in-the-loop flow; the
guards here defensively reject agent attempts to overwrite or delete those
rows if any exist (e.g. created via Django admin during dogfood).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from products.signals.backend.models import SignalMemory

# TTL bounds on agent-written entries. The default of 7 days matches the spec;
# a hard upper bound prevents an over-eager agent from creating effectively-
# permanent rows.
DEFAULT_MEMORY_TTL_DAYS = 7
MAX_MEMORY_TTL_DAYS = 90

# Defensive cap on search results.
DEFAULT_MEMORY_SEARCH_LIMIT = 20
MAX_MEMORY_SEARCH_LIMIT = 100

# Keys/content are agent-chosen prose. Match the model's column lengths so callers
# get a clean error before hitting the DB.
MAX_MEMORY_KEY_LENGTH = 300


class InvalidMemoryError(ValueError):
    """The agent tried to write a memory with invalid shape (empty key, oversized, etc)."""


class HumanConfirmedMemoryError(PermissionError):
    """The agent tried to overwrite or delete a `human_confirmed` entry."""


@dataclass(frozen=True)
class MemoryEntry:
    key: str
    content: str
    authority: str
    tags: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    created_by_run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_memory(
    *,
    team_id: int,
    text: str | None = None,
    tags: list[str] | None = None,
    limit: int = DEFAULT_MEMORY_SEARCH_LIMIT,
    include_expired: bool = False,
) -> list[MemoryEntry]:
    """Return memories the agent should consider when planning a run.

    `text` matches ILIKE against `content`. `tags` filters via Postgres array overlap
    (the GIN index on `tags` makes this cheap). Expired `agent_inference` entries are
    hidden by default; pass `include_expired=True` to surface them for audit/debug.
    """
    clamped_limit = _clamp_search_limit(limit)
    qs = SignalMemory.objects.filter(team_id=team_id)
    if not include_expired:
        # `expires_at IS NULL` is the no-expiry sentinel (only valid for human_confirmed
        # per the model's invariant — we keep them visible).
        qs = qs.filter(_not_expired_clause())
    if text:
        qs = qs.filter(content__icontains=text)
    if tags:
        qs = qs.filter(tags__overlap=list(tags))
    qs = qs.order_by("-updated_at", "-id")[:clamped_limit]
    return [_to_entry(row) for row in qs]


def remember(
    *,
    team_id: int,
    key: str,
    content: str,
    tags: list[str] | None = None,
    ttl_days: int = DEFAULT_MEMORY_TTL_DAYS,
    run_id: str | None = None,
) -> MemoryEntry:
    """Write or update an `agent_inference` memory entry. Idempotent on `(team, key)`.

    The agent never sets `human_confirmed` — that authority class is reserved for
    humans. If a `human_confirmed` row already exists for the key, this raises
    `HumanConfirmedMemoryError` rather than silently overwriting it.
    """
    _validate_key_content(key, content)
    clamped_ttl = _clamp_ttl_days(ttl_days)
    expires_at = timezone.now() + timedelta(days=clamped_ttl)
    normalized_tags = [t for t in (tags or []) if t]

    with transaction.atomic():
        existing = SignalMemory.objects.select_for_update().filter(team_id=team_id, key=key).first()
        if existing is not None and existing.authority == SignalMemory.Authority.HUMAN_CONFIRMED:
            raise HumanConfirmedMemoryError(f"Cannot overwrite human-confirmed memory '{key}' on team {team_id}")
        if existing is None:
            row = SignalMemory.objects.create(
                team_id=team_id,
                key=key,
                content=content,
                authority=SignalMemory.Authority.AGENT_INFERENCE,
                tags=normalized_tags,
                expires_at=expires_at,
                created_by_run_id=run_id,
            )
        else:
            existing.content = content
            existing.tags = normalized_tags
            existing.expires_at = expires_at
            # Authority stays `agent_inference` — we already rejected human-confirmed above.
            # Don't overwrite `created_by_run` so we keep the original creator's lineage.
            existing.save(update_fields=["content", "tags", "expires_at", "updated_at"])
            row = existing
    return _to_entry(row)


def forget(*, team_id: int, key: str) -> bool:
    """Delete an `agent_inference` entry by key. Returns whether anything was removed.

    Does NOT delete `human_confirmed` entries — raises `HumanConfirmedMemoryError`.
    Returns False if the key doesn't exist (no-op).
    """
    with transaction.atomic():
        existing = SignalMemory.objects.select_for_update().filter(team_id=team_id, key=key).first()
        if existing is None:
            return False
        if existing.authority == SignalMemory.Authority.HUMAN_CONFIRMED:
            raise HumanConfirmedMemoryError(f"Cannot forget human-confirmed memory '{key}' on team {team_id}")
        existing.delete()
    return True


def _validate_key_content(key: str, content: str) -> None:
    if not key or not key.strip():
        raise InvalidMemoryError("memory key must be non-empty")
    if len(key) > MAX_MEMORY_KEY_LENGTH:
        raise InvalidMemoryError(f"memory key length {len(key)} exceeds max {MAX_MEMORY_KEY_LENGTH}")
    if not content or not content.strip():
        raise InvalidMemoryError("memory content must be non-empty")


def _clamp_ttl_days(ttl_days: int) -> int:
    if ttl_days < 1:
        return 1
    if ttl_days > MAX_MEMORY_TTL_DAYS:
        return MAX_MEMORY_TTL_DAYS
    return ttl_days


def _clamp_search_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_MEMORY_SEARCH_LIMIT:
        return MAX_MEMORY_SEARCH_LIMIT
    return limit


def _not_expired_clause() -> Q:
    return Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())


def _to_entry(row: SignalMemory) -> MemoryEntry:
    # Django's FK descriptor exposes both `created_by_run` (object) and `created_by_run_id`
    # (the raw FK column). `getattr` keeps Pyright happy without a join.
    run_pk = getattr(row, "created_by_run_id", None)
    return MemoryEntry(
        key=row.key,
        content=row.content,
        authority=row.authority,
        tags=list(row.tags or []),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_by_run_id=str(run_pk) if run_pk else None,
    )
