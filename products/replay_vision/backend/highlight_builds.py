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
# Earlier builds stay readable this long, so a reader scrolling through an older build keeps its pages.
BUILD_RETENTION = timedelta(hours=2)
ISSUE_CODES = (RankCategory.FAILURE, RankCategory.STRUGGLE, RankCategory.REVENUE)


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
        -- Reach counts only rows every viewer may read, so it is the same for every viewer.
        reach AS (
            SELECT group_root, count(*) AS sessions, count(DISTINCT person_key) AS people
            FROM ranked_rows
            WHERE category = ANY(%s) AND experiment_id = 0
            GROUP BY group_root
        ),
        placed AS (
            SELECT bounds.window_days, ranked_rows.*,
                count(*) OVER scanner_window AS scanner_rows,
                row_number() OVER (scanner_window ORDER BY contrast DESC, observation_id DESC) AS place
            FROM ranked_rows
            JOIN bounds ON ranked_rows.created_at >= bounds.window_start AND ranked_rows.created_at <= bounds.window_end
            WINDOW scanner_window AS (PARTITION BY bounds.window_days, ranked_rows.scanner_id)
        )
        SELECT window_days, place, observation_id, scanner_id, created_at, category, experiment_id,
            ((scanner_rows - place + 1) - 0.5) / scanner_rows::double precision AS percentile,
            placed.group_root, COALESCE(reach.sessions, 1), COALESCE(reach.people, 1)
        FROM placed
        LEFT JOIN reach ON reach.group_root = placed.group_root
        WHERE scanner_rows >= %s
            AND place <= least(floor(scanner_rows * %s)::int + 1, %s)
            AND ((scanner_rows - place + 1) - 0.5) / scanner_rows::double precision >= %s
    """
    params: list[Any] = [value for bounds in windows for value in (bounds.window_days, bounds.start, bounds.end)]
    params += [
        resolve_effective_team_id(team_id),
        anchor_version,
        list(ISSUE_CODES),
        MIN_SCANNER_ROWS,
        1 - MIN_PERCENTILE,
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


def build_highlight_feed(team_id: int, anchor_version: int, now: datetime | None = None) -> int:
    """Rank the team's preset windows as of `now`, store them as a new build, and make it current. Returns the build's
    generation."""
    now = now or timezone.now()
    row_team_id = resolve_effective_team_id(team_id)
    generation = int(now.timestamp())
    sql, params = _ranked_sql(team_id, anchor_version, preset_windows(now))
    with transaction.atomic():
        state, _ = (
            ReplayHighlightFeedState.objects.for_team(team_id)
            .select_for_update()
            .get_or_create(team_id=row_team_id, defaults={"generation": 0})
        )
        # A build of the same second already holds this generation, so its entries stand.
        if state.generation >= generation:
            return state.generation
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
        # The build this one replaces stays too, so a reader on it keeps its pages until the next build.
        ReplayHighlightFeedEntry.objects.for_team(team_id).filter(
            generation__lt=min(state.generation, int((now - BUILD_RETENTION).timestamp()))
        ).delete()
        state.generation = generation
        state.built_at = now
        state.save(update_fields=["generation", "built_at"])
    return generation
