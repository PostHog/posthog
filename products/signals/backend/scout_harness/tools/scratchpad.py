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
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction

from products.signals.backend.models import SignalScratchpad
from products.signals.backend.scout_harness.tools.runs import _build_task_url

# Defensive cap on search results.
DEFAULT_SCRATCHPAD_SEARCH_LIMIT = 20
MAX_SCRATCHPAD_SEARCH_LIMIT = 500

# Keys/content are agent-chosen prose. Match the model's column lengths so callers
# get a clean error before hitting the DB.
MAX_SCRATCHPAD_KEY_LENGTH = 300

# `content` is an unbounded TextField read verbatim into future-run prompts — cap it so a
# runaway write can't bloat the scratchpad or a later prompt. Generous for prose.
MAX_SCRATCHPAD_CONTENT_LENGTH = 50_000


class InvalidScratchpadError(ValueError):
    """The agent tried to write a memory with invalid shape (empty key, oversized, etc)."""


@dataclass(frozen=True)
class ScratchpadEntry:
    key: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None
    created_by_run_id: str | None = None
    # Identity + deep-link of the scout run that created the entry, resolved from `created_by_run`.
    created_by_skill: str | None = None
    created_by_run_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_scratchpad(
    *,
    team_id: int,
    text: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = DEFAULT_SCRATCHPAD_SEARCH_LIMIT,
    keys_only: bool = False,
    content_max_chars: int | None = None,
) -> list[ScratchpadEntry]:
    """Return memories the agent should consider when planning a run, newest first.

    `text` matches ILIKE against `content` and `key`. The previous `tags` filter
    + GIN index were dropped in PR 2 review.

    `date_from` / `date_to` are a half-open window on `updated_at` (the entry's
    sort key) — `updated_at >= date_from` and `updated_at < date_to`. Pass `date_to`
    (the `updated_at` of the oldest entry seen) to walk backwards past the result
    cap on subsequent calls (cursor-style iteration), mirroring `search_recent_runs`.

    Result-scoping projections keep an orientation/dedupe scan from pulling every
    entry's full body — `content` is an unbounded TextField, so a wide scan can
    return up to `MAX_SCRATCHPAD_CONTENT_LENGTH × limit` characters of prose the
    caller doesn't need yet:
    - `keys_only=True` blanks `content` entirely — return just keys + metadata to
      pick the entries worth a full read, then re-query the chosen ones.
    - `content_max_chars=N` truncates each `content` to the first `N` characters
      (a preview). Ignored when `keys_only=True`, which already drops the body.
    """
    clamped_limit = _clamp_search_limit(limit)
    # Join the creating run (and its task_run) so per-row skill/url resolution in `_to_entry`
    # stays a single query rather than an N+1 across the result window.
    qs = SignalScratchpad.objects.filter(team_id=team_id).select_related("created_by_run", "created_by_run__task_run")
    if text:
        from django.db.models import Q

        qs = qs.filter(Q(content__icontains=text) | Q(key__icontains=text))
    if date_from is not None:
        qs = qs.filter(updated_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(updated_at__lt=date_to)
    qs = qs.order_by("-updated_at", "-id")[:clamped_limit]
    return [_to_entry(row, keys_only=keys_only, content_max_chars=content_max_chars) for row in qs]


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
    if len(content) > MAX_SCRATCHPAD_CONTENT_LENGTH:
        raise InvalidScratchpadError(
            f"memory content length {len(content)} exceeds max {MAX_SCRATCHPAD_CONTENT_LENGTH}"
        )


def _clamp_search_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_SCRATCHPAD_SEARCH_LIMIT:
        return MAX_SCRATCHPAD_SEARCH_LIMIT
    return limit


def _to_entry(
    row: SignalScratchpad, *, keys_only: bool = False, content_max_chars: int | None = None
) -> ScratchpadEntry:
    # Django's FK descriptor exposes both `created_by_run` (object) and `created_by_run_id`
    # (the raw FK column). `getattr` keeps Pyright happy without a join.
    run_pk = getattr(row, "created_by_run_id", None)
    # Resolve the creating scout's identity + a deep-link to its run. `search_scratchpad` joins
    # both via select_related, so this is a no-N+1 read on the list path; the single-row write
    # path lazy-loads, which is fine. A human-authored entry (no run) leaves these null.
    run = row.created_by_run if run_pk else None
    task_run = getattr(run, "task_run", None) if run is not None else None
    return ScratchpadEntry(
        key=row.key,
        content=_project_content(row.content, keys_only=keys_only, content_max_chars=content_max_chars),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        created_by_run_id=str(run_pk) if run_pk else None,
        created_by_skill=run.skill_name if run is not None else None,
        created_by_run_url=_build_task_url(
            team_id=row.team_id,
            task_id=str(task_run.task_id) if task_run is not None else None,
            task_run_id=str(task_run.id) if task_run is not None else None,
        ),
    )


def _project_content(content: str, *, keys_only: bool, content_max_chars: int | None) -> str:
    """Apply the search projection to a row's `content`: blank it for `keys_only`,
    or truncate to a preview for `content_max_chars`. A negative max clamps to 0."""
    if keys_only:
        return ""
    if content_max_chars is None:
        return content
    return content[: max(content_max_chars, 0)]
