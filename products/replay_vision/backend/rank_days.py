"""Counts each scanner's ranked observations per UTC day, so the feed reads a row's percentile from a few day rows.

Every rank write adds its row here in the same transaction, and the backfill recounts days from the rows themselves.
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import batched
from typing import Any

from django.db import connection
from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import TruncDate

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

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
    for chunk in batched(days.items(), _WRITE_CHUNK, strict=False):
        values = ", ".join(["(%s, %s, %s, %s, %s)"] * len(chunk))
        params: list[Any] = []
        for (scanner_id, day), count in chunk:
            params += [row_team_id, scanner_id, anchor_version, day, count]
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
                f"""
                INSERT INTO replay_vision_replayscannerrankday (team_id, scanner_id, anchor_version, day, observation_count)
                VALUES {values}
                ON CONFLICT (scanner_id, anchor_version, day) DO UPDATE SET
                    observation_count = replay_vision_replayscannerrankday.observation_count + EXCLUDED.observation_count
                """,
                params,
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
    # Ranges on created_at, not a day function, so the count reads the ranked rows' scanner index.
    edges = ranked.filter(
        Q(created_at__lt=_midnight(first_day + timedelta(days=1))) | Q(created_at__gte=_midnight(last_day))
    )
    edge_rows = edges.values("scanner_id").annotate(rows=Count("id")).values_list("scanner_id", "rows")
    counts.update(dict(edge_rows))
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
