"""Ranks a team's highlight feed windows from its rank rows, and stores each preset window as a build that page loads
read instead of ranking the window themselves.

A row's percentile is its place among every ranked row its scanner has in the window, so one statement places all four
preset windows from a single read of the longest one. A build keeps only rows that clear the percentile cut, up to a
bounded number of places per scanner, which is all a page load can reach.
"""

from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.models.replay_highlight_feed import (
    HighlightWindow,
    ReplayHighlightFeedEntry,
    ReplayHighlightFeedState,
)
from products.replay_vision.backend.models.replay_observation_rank import RankCategory

# The feed surfaces a scanner's top fifth by score, once the scanner has enough ranked rows to make a percentile mean
# something.
MIN_PERCENTILE = 0.8
MIN_SCANNER_ROWS = 10
# Page loads read places round-robin across scanners, so no load reaches deeper than this into one scanner.
MAX_PLACES_PER_SCANNER = 500
ISSUE_CODES = (RankCategory.FAILURE, RankCategory.STRUGGLE, RankCategory.REVENUE)
# Namespaces the per-team advisory lock that keeps two builds of one team from running at once.
_BUILD_LOCK_KEY = 0x52564842


@frozen
class RankedEntry:
    window_days: int
    place: int
    observation_id: Any
    scanner_id: Any
    created_at: datetime
    category: int
    experiment_id: int
    percentile: float
    group_root: Any
    group_sessions: int
    group_people: int


@frozen
class WindowBounds:
    window_days: int
    start: datetime
    end: datetime


def _ranked_sql(team_id: int, anchor_version: int, windows: list[WindowBounds]) -> tuple[str, list[Any]]:
    """A SELECT of every kept entry of `windows`, ranked from the team's rank rows, in `RankedEntry` field order."""
    window_values = ", ".join(["(%s::smallint, %s::timestamptz, %s::timestamptz)"] * len(windows))
    sql = f"""
        WITH bounds(window_days, window_start, window_end) AS (VALUES {window_values}),
        ranked_rows AS MATERIALIZED (
            SELECT observation_id, scanner_id, created_at, contrast, category, experiment_id, person_key,
                COALESCE(feed_group_id, observation_id) AS group_root
            FROM replay_vision_replayobservationrank
            WHERE team_id = %s AND anchor_version = %s
                AND created_at >= (SELECT min(window_start) FROM bounds)
                AND created_at <= (SELECT max(window_end) FROM bounds)
        ),
        windowed AS (
            SELECT bounds.window_days, ranked_rows.*
            FROM ranked_rows
            JOIN bounds ON ranked_rows.created_at >= bounds.window_start AND ranked_rows.created_at <= bounds.window_end
        ),
        -- Reach counts only rows every viewer may read, so it is the same for every viewer.
        reach AS (
            SELECT window_days, group_root, count(*) AS sessions, count(DISTINCT person_key) AS people
            FROM windowed
            WHERE category = ANY(%s) AND experiment_id = 0
            GROUP BY window_days, group_root
        ),
        placed AS (
            SELECT windowed.*, ((scanner_rows - place + 1) - 0.5) / scanner_rows::double precision AS percentile
            FROM (
                SELECT windowed.*,
                    count(*) OVER scanner_window AS scanner_rows,
                    row_number() OVER (scanner_window ORDER BY contrast DESC, observation_id DESC) AS place
                FROM windowed
                WINDOW scanner_window AS (PARTITION BY window_days, scanner_id)
            ) windowed
        )
        SELECT placed.window_days, place, observation_id, scanner_id, created_at, category, experiment_id, percentile,
            placed.group_root, COALESCE(reach.sessions, 1), COALESCE(reach.people, 1)
        FROM placed
        LEFT JOIN reach ON reach.window_days = placed.window_days AND reach.group_root = placed.group_root
        WHERE scanner_rows >= %s AND place <= %s AND percentile >= %s
    """
    params: list[Any] = [value for bounds in windows for value in (bounds.window_days, bounds.start, bounds.end)]
    params += [
        resolve_effective_team_id(team_id),
        anchor_version,
        list(ISSUE_CODES),
        MIN_SCANNER_ROWS,
        MAX_PLACES_PER_SCANNER,
        MIN_PERCENTILE,
    ]
    return sql, params


def rank_window(team_id: int, anchor_version: int, start: datetime, end: datetime) -> list[RankedEntry]:
    """Rank one arbitrary window the way a build ranks a preset one, without storing it."""
    sql, params = _ranked_sql(team_id, anchor_version, [WindowBounds(window_days=0, start=start, end=end)])
    with connection.cursor() as cursor:
        # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
        cursor.execute(sql, params)
        names = [field.name for field in fields(RankedEntry)]
        return [RankedEntry(**dict(zip(names, row))) for row in cursor.fetchall()]


def preset_windows(now: datetime) -> list[WindowBounds]:
    return [
        WindowBounds(window_days=days, start=now - timedelta(days=days), end=now) for days in HighlightWindow.values
    ]


def build_highlight_feed(team_id: int, anchor_version: int, *, wait: bool = True, force: bool = False) -> int | None:
    """Rank the team's preset windows as of now, store them as a new build, and make it current. Returns the current
    generation, or None when `wait` is off and another build of the team holds the lock.

    A team built since its ranks last changed keeps its build unless `force` is set, so a build that waited on another
    one does not repeat it. The state row is held only for the final swap, so rank writes never wait on the ranking.
    """
    row_team_id = resolve_effective_team_id(team_id)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)" if wait else "SELECT pg_try_advisory_xact_lock(%s, %s)",
                [_BUILD_LOCK_KEY, row_team_id],
            )
            locked = cursor.fetchone()[0]
        state, _ = ReplayHighlightFeedState.objects.for_team(team_id).get_or_create(team_id=row_team_id)
        if locked is False:
            return None
        if not force and state.built_at is not None and state.changes <= state.built_changes:
            return state.generation
        now = timezone.now()
        generation = state.generation + 1
        sql, params = _ranked_sql(team_id, anchor_version, preset_windows(now))
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
                f"""
                INSERT INTO replay_vision_replayhighlightfeedentry (
                    team_id, generation, window_days, place, observation_id, scanner_id, created_at, category,
                    experiment_id, percentile, group_root, group_sessions, group_people
                )
                SELECT %s, %s, ranked.* FROM ({sql}) ranked
                """,
                [row_team_id, generation, *params],
            )
        # The build this one replaces stays, so a reader who started on it keeps its pages until the next build.
        ReplayHighlightFeedEntry.objects.for_team(team_id).filter(generation__lt=state.generation).delete()
        ReplayHighlightFeedState.objects.for_team(team_id).filter(team_id=row_team_id).update(
            previous_generation=state.generation,
            generation=generation,
            built_at=timezone.now(),
            built_changes=state.changes,
        )
    return generation
