"""Moves focused and balanced scanners to comprehensive mode, scaling each rate by its team's pass share so volume holds."""

import math
from collections.abc import Sequence
from typing import Any

from django.db import transaction

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, SamplingMode
from products.replay_vision.backend.queries.scanner_candidate_query import MIN_SAMPLING_RATE, SAMPLE_RATE_PRECISION
from products.replay_vision.backend.session_limits import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)

# The candidate query read an unscored session as this mid-pack score, so the filter kept it.
UNSCORED_SURFACING_SCORE = 0.36
FOCUSED_SURFACING_THRESHOLD = 0.30
BALANCED_SURFACING_THRESHOLD = 0.10

# Scores only exist for sessions from the last seven days, so a longer window adds unscored sessions.
PASS_SHARE_LOOKBACK_DAYS = 7

# Below this many sessions a team's share is noise, so the pooled share of all teams applies.
MIN_TEAM_SESSIONS = 100

_RETIRED_MODES = (SamplingMode.FOCUSED, SamplingMode.BALANCED)

_TEAMS_PER_QUERY = 200
_QUERY_TIMEOUT_S = 300

# Pooled across every team, so the fallback does not depend on which scanners one run selects.
POOLED_SHARE_LOOKBACK_DAYS = 1

_ELIGIBLE_SESSIONS_SQL = """
    SELECT
        team_id,
        session_id,
        coalesce(max(surfacing_score), %(unscored_score)s) AS score,
        dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) AS duration_s,
        sum(active_milliseconds) / 1000 AS active_s
    FROM session_replay_events
    WHERE {team_filter} min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s)
    GROUP BY team_id, session_id
    HAVING duration_s >= %(min_duration_s)s
       AND active_s >= %(min_active_s)s
       AND active_s <= %(max_active_s)s
"""

_KEPT_COUNTS = """
    count() AS sessions,
    countIf(score >= %(focused_threshold)s) AS focused_kept,
    countIf(score >= %(balanced_threshold)s) AS balanced_kept
"""

_TEAM_PASS_SHARES_SQL = (
    "SELECT team_id,"
    + _KEPT_COUNTS
    + "FROM ("
    + _ELIGIBLE_SESSIONS_SQL.format(team_filter="team_id IN %(team_ids)s AND")
    + ") GROUP BY team_id"
)

_POOLED_PASS_SHARES_SQL = "SELECT" + _KEPT_COUNTS + "FROM (" + _ELIGIBLE_SESSIONS_SQL.format(team_filter="") + ")"


@frozen
class PassShares:
    """Share of a team's scanner-eligible sessions that each quality mode kept."""

    focused: float
    balanced: float

    def for_mode(self, sampling_mode: str) -> float:
        return self.focused if sampling_mode == SamplingMode.FOCUSED else self.balanced


@frozen
class RetiredScanner:
    scanner_id: str
    team_id: int
    sampling_mode: str
    old_rate: float
    new_rate: float
    pooled_share: bool


def retired_sampling_rate(rate: float, pass_share: float) -> float:
    """The rate that scans as many sessions without the filter as `rate` scanned with it."""
    if rate <= 0:
        return 0.0
    scaled = math.floor(rate * pass_share * SAMPLE_RATE_PRECISION) / SAMPLE_RATE_PRECISION
    # The model rejects a non-zero rate below the minimum, and zero would turn a scanner off.
    return min(rate, max(MIN_SAMPLING_RATE, scaled))


def _query(sql: str, extra_params: dict[str, Any], lookback_days: int) -> list[tuple]:
    with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_sampling_mode_retirement"):
        return sync_execute(
            sql,
            {
                "focused_threshold": FOCUSED_SURFACING_THRESHOLD,
                "balanced_threshold": BALANCED_SURFACING_THRESHOLD,
                "unscored_score": UNSCORED_SURFACING_SCORE,
                "lookback_days": lookback_days,
                "min_duration_s": MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
                "min_active_s": MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
                "max_active_s": MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
                **extra_params,
            },
            ch_user=ClickHouseUser.REPLAY_VISION,
            settings={"max_execution_time": _QUERY_TIMEOUT_S},
            workload=Workload.OFFLINE,
        )


def _shares(sessions: int, focused_kept: int, balanced_kept: int) -> PassShares:
    if sessions == 0:
        # No data at all means no basis to cut a rate, so rates stay as they are.
        return PassShares(focused=1.0, balanced=1.0)
    return PassShares(focused=focused_kept / sessions, balanced=balanced_kept / sessions)


def team_pass_shares(team_ids: Sequence[int]) -> tuple[dict[int, PassShares], PassShares | None]:
    """Per-team pass shares for teams with enough sessions, and the pooled share of all teams when any team lacks one."""
    by_team: dict[int, PassShares] = {}
    for start in range(0, len(team_ids), _TEAMS_PER_QUERY):
        batch = list(team_ids[start : start + _TEAMS_PER_QUERY])
        for team_id, sessions, focused_kept, balanced_kept in _query(
            _TEAM_PASS_SHARES_SQL, {"team_ids": batch}, PASS_SHARE_LOOKBACK_DAYS
        ):
            if sessions >= MIN_TEAM_SESSIONS:
                by_team[int(team_id)] = _shares(int(sessions), int(focused_kept), int(balanced_kept))
    if all(team_id in by_team for team_id in team_ids):
        return by_team, None
    [(sessions, focused_kept, balanced_kept)] = _query(_POOLED_PASS_SHARES_SQL, {}, POOLED_SHARE_LOOKBACK_DAYS)
    return by_team, _shares(int(sessions), int(focused_kept), int(balanced_kept))


def retire_sampling_modes(*, apply: bool, team_ids: Sequence[int] | None = None) -> list[RetiredScanner]:
    """Rescale and switch every focused or balanced scanner, or only report the change when `apply` is false."""
    scanners = ReplayScanner.all_origins.filter(sampling_mode__in=_RETIRED_MODES)
    if team_ids is not None:
        scanners = scanners.filter(team_id__in=team_ids)
    scanners_list = list(scanners)
    if not scanners_list:
        return []
    by_team, pooled = team_pass_shares(sorted({s.team_id for s in scanners_list}))

    retired: list[RetiredScanner] = []
    for scanner in scanners_list:
        if apply:
            with transaction.atomic():
                # Re-read under the row lock, so an edit made during the ClickHouse queries is neither lost nor rescaled twice.
                scanner = ReplayScanner.all_origins.select_for_update().get(pk=scanner.pk)
                if scanner.sampling_mode not in _RETIRED_MODES:
                    continue
                result = _retire(scanner, by_team, pooled)
                # A full save bumps the scanner version, marks the estimate stale and writes the activity log.
                scanner.sampling_rate = result.new_rate
                scanner.sampling_mode = SamplingMode.COMPREHENSIVE
                scanner.save(update_fields=["sampling_rate", "sampling_mode", "updated_at"])
        else:
            result = _retire(scanner, by_team, pooled)
        retired.append(result)
    return retired


def _retire(scanner: ReplayScanner, by_team: dict[int, PassShares], pooled: PassShares | None) -> RetiredScanner:
    shares = by_team.get(scanner.team_id)
    applied = shares if shares is not None else pooled
    # team_pass_shares only skips the pooled query when every selected team has its own share.
    assert applied is not None
    return RetiredScanner(
        scanner_id=str(scanner.id),
        team_id=scanner.team_id,
        sampling_mode=scanner.sampling_mode,
        old_rate=scanner.sampling_rate,
        new_rate=retired_sampling_rate(scanner.sampling_rate, applied.for_mode(scanner.sampling_mode)),
        pooled_share=shares is None,
    )
