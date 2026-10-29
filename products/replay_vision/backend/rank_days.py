"""Counts each scanner's ranked observations per UTC day, so the feed reads a row's percentile from a few day rows.

Every rank write adds its row here in the same transaction, and the backfill recounts days from the rows themselves.
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, QuerySet, Sum
from django.db.models.functions import TruncDate

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.cluster_membership import add_day_counts
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner_rank_day import ReplayScannerRankDay

_WRITE_CHUNK = 500


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


@frozen
class RankedRow:
    scanner_id: uuid.UUID
    created_at: datetime


def add_rank_days(team_id: int, anchor_version: int, rows: Iterable[RankedRow]) -> None:
    """Count newly ranked rows into their scanners' days, in the caller's transaction."""
    days = Counter((row.scanner_id, row.created_at.astimezone(UTC).date()) for row in rows)
    if not days:
        return
    row_team_id = resolve_effective_team_id(team_id)
    add_day_counts(
        "replay_vision_replayscannerrankday",
        ["team_id", "scanner_id", "anchor_version", "day", "observation_count"],
        ["scanner_id", "anchor_version", "day"],
        [(row_team_id, scanner_id, anchor_version, day, count) for (scanner_id, day), count in days.items()],
    )


def scanner_rank_counts(
    ranked: QuerySet[ReplayObservation],
    team_id: int,
    anchor_version: int,
    scanner_ids: Sequence[Any],
    date_from: datetime,
    date_to: datetime,
) -> dict[uuid.UUID, int]:
    """Each scanner's ranked rows in the window: whole days from the day counts, the two edge days counted exactly.

    `ranked` holds the window's ranked rows, so the edge counts apply the same filters as the picks.
    """
    first_day = date_from.astimezone(UTC).date()
    last_day = date_to.astimezone(UTC).date()
    counts: Counter[uuid.UUID] = Counter()
    if last_day - first_day > timedelta(days=1):
        inner = (
            ReplayScannerRankDay.objects.for_team(team_id)
            .filter(
                scanner_id__in=scanner_ids,
                anchor_version=anchor_version,
                day__gt=first_day,
                day__lt=last_day,
            )
            .values("scanner_id")
            .annotate(rows=Sum("observation_count"))
            .values_list("scanner_id", "rows")
        )
        counts.update(dict(inner))
    # Each edge is its own created_at range, so both counts read the ranked rows' scanner index in one statement.
    first_edge = ranked.filter(created_at__lt=_midnight(first_day + timedelta(days=1)))
    edges = [first_edge]
    if last_day > first_day:
        edges.append(ranked.filter(created_at__gte=_midnight(last_day)))
    by_scanner = [
        edge.order_by().values("scanner_id").annotate(rows=Count("id")).values_list("scanner_id", "rows")
        for edge in edges
    ]
    for scanner_id, rows in by_scanner[0].union(*by_scanner[1:], all=True):
        counts[scanner_id] += rows
    return dict(counts)


@frozen
class RankDayBackfillResult:
    days: int


def backfill_team_rank_days(
    team_id: int, since: datetime, anchor_version: int, *, dry_run: bool = False
) -> RankDayBackfillResult:
    """Recount the team's ranked rows per scanner and day since `since`, replacing the stored day counts.

    A rank the consumer writes during the recount can land in both, which overcounts that day by one row until the
    next recount.
    """
    first_day = since.astimezone(UTC).date()
    days = list(
        ReplayObservation.objects.filter(
            team_id=team_id,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=_midnight(first_day),
            watch_rank__isnull=False,
            watch_rank__anchor_version=anchor_version,
        )
        .annotate(rank_day=TruncDate("created_at", tzinfo=UTC))
        .values("scanner_id", "rank_day")
        .annotate(rows=Count("id"))
        .values_list("scanner_id", "rank_day", "rows")
    )
    if dry_run:
        return RankDayBackfillResult(days=len(days))
    row_team_id = resolve_effective_team_id(team_id)
    ReplayScannerRankDay.objects.for_team(team_id).bulk_create(
        [
            ReplayScannerRankDay(
                team_id=row_team_id,
                scanner_id=scanner_id,
                anchor_version=anchor_version,
                day=day,
                observation_count=rows,
            )
            for scanner_id, day, rows in days
        ],
        batch_size=_WRITE_CHUNK,
        update_conflicts=True,
        unique_fields=["scanner", "anchor_version", "day"],
        update_fields=["observation_count"],
    )
    return RankDayBackfillResult(days=len(days))
