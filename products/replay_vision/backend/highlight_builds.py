"""Ranks a team's highlight feed windows from its rank rows, and stores each preset window as a build that page loads
read instead of ranking the window themselves.

A row's percentile is its place among every ranked row its scanner has in the window, so one statement places all four
preset windows from a single read of the longest one. A build keeps only rows that clear the percentile cut, up to a
bounded number of places per scanner, which is all a page load can reach.
"""

from collections.abc import Callable, Sequence
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.models.replay_highlight_feed import (
    HighlightWindow,
    ReplayHighlightFeedEntry,
    ReplayHighlightFeedState,
)
from products.replay_vision.backend.models.replay_observation_rank import RankCategory
from products.replay_vision.backend.observation_ranks import mark_changed

logger = structlog.get_logger(__name__)

# The feed surfaces a scanner's top fifth by score, once the scanner has enough ranked rows to make a percentile mean
# something.
MIN_PERCENTILE = 0.8
MIN_SCANNER_ROWS = 10
# Page loads read places round-robin across scanners, so no load reaches deeper than this into one scanner.
MAX_PLACES_PER_SCANNER = 500
ISSUE_CODES = (RankCategory.FAILURE, RankCategory.STRUGGLE, RankCategory.REVENUE)
# Builds a reader may still be scrolling stay this long after a newer build replaces them.
BUILD_RETENTION = timedelta(minutes=30)
_STATEMENT_TIMEOUT = "120s"
_LOCK_TIMEOUT = "10s"
# A build older than this asks for a rebuild when read, so a quiet team's windows still move forward.
STALE_AFTER = timedelta(hours=1)
# A team waits at least this long after its last build, so a busy team rebuilds a few times an hour.
REBUILD_DEBOUNCE = timedelta(minutes=5)
REBUILDS_PER_SWEEP = 20
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
    person_key: int | None


@frozen
class WindowBounds:
    window_days: int
    start: datetime
    end: datetime


def _ranked_sql(
    team_id: int,
    anchor_version: int,
    windows: list[WindowBounds],
    scanner_ids: Sequence[Any] | None = None,
    ranked_before: datetime | None = None,
) -> tuple[str, list[Any]]:
    """A SELECT of every kept entry of `windows`, ranked from the team's rank rows, in `RankedEntry` field order.
    `scanner_ids` and `ranked_before` narrow the rows before ranking."""
    window_values = ", ".join(["(%s::smallint, %s::timestamptz, %s::timestamptz)"] * len(windows))
    narrowing = ""
    narrowing_params: list[Any] = []
    if scanner_ids is not None:
        narrowing += " AND scanner_id = ANY(%s::uuid[])"
        narrowing_params.append([str(scanner_id) for scanner_id in scanner_ids])
    if ranked_before is not None:
        narrowing += " AND ranked_at <= %s"
        narrowing_params.append(ranked_before)
    sql = f"""
        WITH bounds(window_days, window_start, window_end) AS (VALUES {window_values}),
        ranked_rows AS MATERIALIZED (
            SELECT observation_id, scanner_id, created_at, contrast, category, experiment_id,
                COALESCE(feed_group_id, observation_id) AS group_root, person_key
            FROM replay_vision_replayobservationrank
            WHERE team_id = %s AND anchor_version = %s
                AND created_at >= (SELECT min(window_start) FROM bounds)
                AND created_at <= (SELECT max(window_end) FROM bounds){narrowing}
        ),
        windowed AS (
            SELECT bounds.window_days, ranked_rows.*
            FROM ranked_rows
            JOIN bounds ON ranked_rows.created_at >= bounds.window_start AND ranked_rows.created_at <= bounds.window_end
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
        SELECT window_days, place, observation_id, scanner_id, created_at, category, experiment_id, percentile,
            group_root, person_key
        FROM placed
        WHERE scanner_rows >= %s AND place <= %s AND percentile >= %s
    """
    params: list[Any] = [value for bounds in windows for value in (bounds.window_days, bounds.start, bounds.end)]
    params += [
        resolve_effective_team_id(team_id),
        anchor_version,
        *narrowing_params,
        MIN_SCANNER_ROWS,
        MAX_PLACES_PER_SCANNER,
        MIN_PERCENTILE,
    ]
    return sql, params


def rank_window(
    team_id: int,
    anchor_version: int,
    start: datetime,
    end: datetime,
    scanner_ids: Sequence[Any] | None = None,
    ranked_before: datetime | None = None,
) -> list[RankedEntry]:
    """Rank one arbitrary window the way a build ranks a preset one, without storing it. `scanner_ids` ranks only those
    scanners, which ranks each the same since a percentile is within its scanner."""
    if scanner_ids is not None and not scanner_ids:
        return []
    window = WindowBounds(window_days=0, start=start, end=end)
    sql, params = _ranked_sql(team_id, anchor_version, [window], scanner_ids, ranked_before)
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
            # A stuck statement or lock fails the build instead of stalling every build behind it.
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
                [_STATEMENT_TIMEOUT, _LOCK_TIMEOUT],
            )
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)" if wait else "SELECT pg_try_advisory_xact_lock(%s, %s)",
                [_BUILD_LOCK_KEY, row_team_id],
            )
            if cursor.fetchone()[0] is False:
                return None
        state, _ = ReplayHighlightFeedState.objects.for_team(team_id).get_or_create(team_id=row_team_id)
        if not force and state.built_at is not None and state.changes <= state.built_changes:
            return state.generation
        seen_changes = state.changes
        generation = state.generation + 1
        sql, params = _ranked_sql(team_id, anchor_version, preset_windows(timezone.now()))
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
                f"""
                INSERT INTO replay_vision_replayhighlightfeedentry (
                    team_id, generation, window_days, place, observation_id, scanner_id, created_at, category,
                    experiment_id, percentile, group_root, person_key
                )
                SELECT %s, %s, ranked.* FROM ({sql}) ranked
                """,
                [row_team_id, generation, *params],
            )
        built_at = timezone.now()
        # A build stays while a reader who started on it may still be scrolling, and the newest one always stays.
        kept = [
            build
            for build in state.builds
            if datetime.fromisoformat(build[1]) > built_at - BUILD_RETENTION or build[0] == state.generation
        ]
        kept.append([generation, built_at.isoformat()])
        ReplayHighlightFeedEntry.objects.for_team(team_id).exclude(generation__in=[build[0] for build in kept]).delete()
        ReplayHighlightFeedState.objects.for_team(team_id).filter(team_id=row_team_id).update(
            generation=generation, built_at=built_at, builds=kept, built_changes=seen_changes
        )
    return generation


def stored_generation(team_id: int, anchor_version: int, as_of: datetime) -> int | None:
    """The stored build a load at `as_of` reads: the newest kept build that was current by then, so later pages stay on
    the build the first page read. A team without a build gets one first, and a stale build is served as is and asks
    for a rebuild. None when the team's first build is still running elsewhere."""
    state = ReplayHighlightFeedState.objects.for_team(team_id).first()
    if state is None or state.built_at is None:
        # A first build another request already runs is not waited on; this load ranks its window on the spot.
        return build_highlight_feed(team_id, anchor_version, wait=False)
    if state.built_at < timezone.now() - STALE_AFTER and state.changes <= state.built_changes:
        mark_changed(team_id)
    current_by_then = [build[0] for build in state.builds if datetime.fromisoformat(build[1]) <= as_of]
    # A load that began before any kept build reads the oldest one, which its first page built or read.
    return max(current_by_then) if current_by_then else min(build[0] for build in state.builds)


def rebuild_changed_feeds(anchor_version: int, *, on_team: Callable[[], bool] | None = None) -> int:
    """Rebuild teams whose ranks changed since their last build, least recently tried first, skipping any team another
    process is building. A team whose build fails waits behind the others. `on_team` runs before each team's build, and
    a false return stops the sweep.
    Returns how many it built."""
    now = timezone.now()
    states = ReplayHighlightFeedState.objects.unscoped()
    due = list(
        # Every team's state, since the sweep picks which teams to build.
        states.filter(changes__gt=F("built_changes"))
        .filter(Q(built_at__isnull=True) | Q(built_at__lt=now - REBUILD_DEBOUNCE))
        .filter(Q(attempted_at__isnull=True) | Q(attempted_at__lt=now - REBUILD_DEBOUNCE))
        .order_by(F("attempted_at").asc(nulls_first=True))
        .values_list("team_id", flat=True)[:REBUILDS_PER_SWEEP]
    )
    states.filter(team_id__in=due).update(attempted_at=now)
    built = 0
    for team_id in due:
        if on_team is not None and not on_team():
            break
        try:
            built += build_highlight_feed(team_id, anchor_version, wait=False) is not None
        except Exception:
            # One team's failing build must not hold up every team behind it.
            logger.exception("replay_vision.highlight_builds.rebuild_failed", team_id=team_id)
    return built
