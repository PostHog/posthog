"""Writes a member's feed group and search theme onto its observation and counts it in its cluster's day.

The consumer and the backfills both write through here, so a cluster's daily counts always match the observations
that carry its id.
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from itertools import batched
from typing import Any

from django.db import connection, transaction

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
)

_WRITE_CHUNK = 500
_BACKFILL_CHUNK = 2_000


@frozen
class Membership:
    observation_id: uuid.UUID
    created_at: datetime
    group_id: uuid.UUID
    theme_id: uuid.UUID | None
    category: str
    contrast: float
    variant: str
    experiment_id: int


def experiment_id_of(snapshot: dict[str, Any] | None) -> int:
    """The experiment an observation was scanned for, or 0 when it was scanned without experiment targeting."""
    snapshot = snapshot or {}
    for store in ("experiment_targeting", "scanner_config"):
        experiment_id = (snapshot.get(store) or {}).get("experiment_id")
        if isinstance(experiment_id, int) and not isinstance(experiment_id, bool):
            return experiment_id
    return 0


def variant_of(scanner_result: dict[str, Any] | None) -> str:
    variant = (scanner_result or {}).get("experiment_variant")
    return variant if isinstance(variant, str) else ""


def record_memberships(
    team_id: int,
    memberships: Iterable[Membership],
    *,
    live_groups: set[uuid.UUID] | None = None,
    live_themes: set[uuid.UUID] | None = None,
) -> None:
    """Set each observation's cluster ids and add it to its clusters' day counts, in the caller's transaction.

    The live sets, when given, leave out the day counts of clusters already pruned, which a backfill meets in old rows.
    """
    members = list(memberships)
    if not members:
        return
    ReplayObservation.objects.bulk_update(
        [ReplayObservation(id=m.observation_id, feed_group_id=m.group_id, search_theme_id=m.theme_id) for m in members],
        ["feed_group_id", "search_theme_id"],
        batch_size=_WRITE_CHUNK,
    )
    row_team_id = resolve_effective_team_id(team_id)
    group_days: Counter[tuple[uuid.UUID, date, str, int, str]] = Counter()
    group_best: dict[tuple[uuid.UUID, date, str, int, str], float] = {}
    theme_days: Counter[tuple[uuid.UUID, date]] = Counter()
    for m in members:
        day = m.created_at.astimezone(UTC).date()
        key = (m.group_id, day, m.variant, m.experiment_id, m.category)
        if live_groups is None or m.group_id in live_groups:
            group_days[key] += 1
            group_best[key] = max(group_best.get(key, m.contrast), m.contrast)
        if m.theme_id is not None and (live_themes is None or m.theme_id in live_themes):
            theme_days[(m.theme_id, day)] += 1
    _add_group_days(row_team_id, [(*key, count, group_best[key]) for key, count in group_days.items()])
    _add_theme_days(row_team_id, [(*key, count) for key, count in theme_days.items()])


def add_day_counts(
    table: str, columns: Sequence[str], conflict: Sequence[str], rows: Iterable[Sequence[Any]], *, also_set: str = ""
) -> None:
    """Add each row's `observation_count` onto the stored day, which an ORM upsert can't express: it only overwrites."""
    placeholders = f"({', '.join(['%s'] * len(columns))})"
    for chunk in batched(rows, _WRITE_CHUNK, strict=False):
        params = [value for row in chunk for value in row]
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (names come from callers' literals, every value is a parameter)
                f"""
                INSERT INTO {table} ({", ".join(columns)})
                VALUES {", ".join([placeholders] * len(chunk))}
                ON CONFLICT ({", ".join(conflict)}) DO UPDATE SET
                    observation_count = {table}.observation_count + EXCLUDED.observation_count{also_set}
                """,
                params,
            )


def _add_group_days(team_id: int, rows: list[tuple[uuid.UUID, date, str, int, str, int, float]]) -> None:
    table = "replay_vision_replayscannerfeedgroupday"
    add_day_counts(
        table,
        ["team_id", "group_id", "day", "variant", "experiment_id", "category", "observation_count", "best_contrast"],
        ["group_id", "day", "variant", "experiment_id", "category"],
        [(team_id, *row) for row in rows],
        also_set=f", best_contrast = GREATEST({table}.best_contrast, EXCLUDED.best_contrast)",
    )


def _add_theme_days(team_id: int, rows: list[tuple[uuid.UUID, date, int]]) -> None:
    add_day_counts(
        "replay_vision_replayscannersearchthemeday",
        ["team_id", "theme_id", "day", "observation_count"],
        ["theme_id", "day"],
        [(team_id, *row) for row in rows],
    )


@frozen
class MembershipBackfillResult:
    observations: int
    recorded: int


def backfill_team_memberships(team_id: int, since: datetime, *, dry_run: bool = False) -> MembershipBackfillResult:
    """Copy the cluster ids the consumer kept only in each ranked row's rank onto the row, and count them by day.

    Rows the consumer wrote after the columns existed already have them, so only rows with a group in the rank and
    none in the column are read, and a rerun after a failure picks up where it stopped.
    """
    pending = (
        ReplayObservation.objects.filter(
            team_id=team_id, created_at__gte=since, feed_group_id__isnull=True, watch_rank__isnull=False
        )
        .filter(watch_rank__has_key="group")
        .order_by("id")
    )
    observations = recorded = 0
    last_id: uuid.UUID | None = None
    while True:
        page = pending.filter(id__gt=last_id) if last_id else pending
        rows = list(
            page.values("id", "created_at", "watch_rank", "scanner_result", "scanner_snapshot")[:_BACKFILL_CHUNK]
        )
        if not rows:
            break
        last_id = rows[-1]["id"]
        memberships = [membership for row in rows if (membership := _membership_from_rank(row)) is not None]
        observations += len(rows)
        if dry_run or not memberships:
            continue
        group_ids = {m.group_id for m in memberships}
        theme_ids = {m.theme_id for m in memberships if m.theme_id}
        with transaction.atomic():
            record_memberships(
                team_id,
                memberships,
                live_groups=set(
                    ReplayScannerFeedGroup.objects.for_team(team_id)
                    .filter(id__in=group_ids)
                    .values_list("id", flat=True)
                ),
                live_themes=set(
                    ReplayScannerSearchTheme.objects.for_team(team_id)
                    .filter(id__in=theme_ids)
                    .values_list("id", flat=True)
                ),
            )
        recorded += len(memberships)
    return MembershipBackfillResult(observations=observations, recorded=recorded)


def _membership_from_rank(row: Mapping[str, Any]) -> Membership | None:
    rank = row["watch_rank"] or {}
    group_id = _uuid_or_none(rank.get("group"))
    if group_id is None:
        return None
    return Membership(
        observation_id=row["id"],
        created_at=row["created_at"],
        group_id=group_id,
        theme_id=_uuid_or_none(rank.get("theme")),
        category=str(rank.get("category") or ""),
        contrast=_contrast(rank),
        variant=variant_of(row["scanner_result"]),
        experiment_id=experiment_id_of(row["scanner_snapshot"]),
    )


def _contrast(rank: Mapping[str, Any]) -> float:
    contrast = rank.get("contrast")
    return float(contrast) if isinstance(contrast, int | float) and not isinstance(contrast, bool) else 0.0


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None
