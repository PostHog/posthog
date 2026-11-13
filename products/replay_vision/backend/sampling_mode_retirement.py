"""Moves focused and balanced scanners to comprehensive mode, scaling each rate by its team's pass share so volume holds."""

import math
from collections.abc import Iterable, Sequence

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.session_recordings.queries.session_recording_list_from_query import UNSCORED_SURFACING_SCORE

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, SamplingMode
from products.replay_vision.backend.queries.scanner_candidate_query import (
    BALANCED_SURFACING_THRESHOLD,
    FOCUSED_SURFACING_THRESHOLD,
    MIN_SAMPLING_RATE,
    SAMPLE_RATE_PRECISION,
)
from products.replay_vision.backend.session_limits import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)

# Scores only exist for sessions from the last seven days, so a longer window adds unscored sessions.
PASS_SHARE_LOOKBACK_DAYS = 7

# Below this many sessions a team's share is noise, so the pooled share of all teams applies.
MIN_TEAM_SESSIONS = 100

_TEAMS_PER_QUERY = 200
_QUERY_TIMEOUT_S = 300

_PASS_SHARES_SQL = """
SELECT
    team_id,
    count() AS sessions,
    countIf(score >= %(focused_threshold)s) AS focused_kept,
    countIf(score >= %(balanced_threshold)s) AS balanced_kept
FROM (
    SELECT
        team_id,
        session_id,
        coalesce(max(surfacing_score), %(unscored_score)s) AS score,
        dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) AS duration_s,
        sum(active_milliseconds) / 1000 AS active_s
    FROM session_replay_events
    WHERE team_id IN %(team_ids)s
      AND min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s)
    GROUP BY team_id, session_id
    HAVING duration_s >= %(min_duration_s)s
       AND active_s >= %(min_active_s)s
       AND active_s <= %(max_active_s)s
)
GROUP BY team_id
"""


@frozen
class PassShares:
    """Share of a team's scanner-eligible sessions that each quality mode kept."""

    focused: float
    balanced: float

    def for_mode(self, sampling_mode: str) -> float:
        return self.focused if sampling_mode == SamplingMode.FOCUSED else self.balanced


@frozen
class _TeamCounts:
    sessions: int
    focused_kept: int
    balanced_kept: int


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


def _fetch_team_counts(team_ids: Sequence[int]) -> dict[int, _TeamCounts]:
    counts: dict[int, _TeamCounts] = {}
    for start in range(0, len(team_ids), _TEAMS_PER_QUERY):
        batch = list(team_ids[start : start + _TEAMS_PER_QUERY])
        with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_sampling_mode_retirement"):
            rows = sync_execute(
                _PASS_SHARES_SQL,
                {
                    "team_ids": batch,
                    "focused_threshold": FOCUSED_SURFACING_THRESHOLD,
                    "balanced_threshold": BALANCED_SURFACING_THRESHOLD,
                    "unscored_score": UNSCORED_SURFACING_SCORE,
                    "lookback_days": PASS_SHARE_LOOKBACK_DAYS,
                    "min_duration_s": MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
                    "min_active_s": MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
                    "max_active_s": MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
                },
                ch_user=ClickHouseUser.REPLAY_VISION,
                settings={"max_execution_time": _QUERY_TIMEOUT_S},
                workload=Workload.OFFLINE,
            )
        for team_id, sessions, focused_kept, balanced_kept in rows:
            counts[int(team_id)] = _TeamCounts(
                sessions=int(sessions), focused_kept=int(focused_kept), balanced_kept=int(balanced_kept)
            )
    return counts


def _pooled_shares(counts: Iterable[_TeamCounts]) -> PassShares:
    sessions = focused = balanced = 0
    for c in counts:
        sessions += c.sessions
        focused += c.focused_kept
        balanced += c.balanced_kept
    if sessions == 0:
        # No data at all means no basis to cut a rate, so rates stay as they are.
        return PassShares(focused=1.0, balanced=1.0)
    return PassShares(focused=focused / sessions, balanced=balanced / sessions)


def team_pass_shares(team_ids: Sequence[int]) -> tuple[dict[int, PassShares], PassShares]:
    """Per-team pass shares for teams with enough sessions, and the pooled share for the rest."""
    counts = _fetch_team_counts(team_ids)
    by_team = {
        team_id: PassShares(focused=c.focused_kept / c.sessions, balanced=c.balanced_kept / c.sessions)
        for team_id, c in counts.items()
        if c.sessions >= MIN_TEAM_SESSIONS
    }
    return by_team, _pooled_shares(counts.values())


def retire_sampling_modes(*, apply: bool, team_ids: Sequence[int] | None = None) -> list[RetiredScanner]:
    """Rescale and switch every focused or balanced scanner, or only report the change when `apply` is false."""
    scanners = ReplayScanner.all_origins.filter(sampling_mode__in=[SamplingMode.FOCUSED, SamplingMode.BALANCED])
    if team_ids is not None:
        scanners = scanners.filter(team_id__in=team_ids)
    scanners_list = list(scanners)
    by_team, pooled = team_pass_shares(sorted({s.team_id for s in scanners_list}))

    retired: list[RetiredScanner] = []
    for scanner in scanners_list:
        shares = by_team.get(scanner.team_id)
        new_rate = retired_sampling_rate(scanner.sampling_rate, (shares or pooled).for_mode(scanner.sampling_mode))
        retired.append(
            RetiredScanner(
                scanner_id=str(scanner.id),
                team_id=scanner.team_id,
                sampling_mode=scanner.sampling_mode,
                old_rate=scanner.sampling_rate,
                new_rate=new_rate,
                pooled_share=shares is None,
            )
        )
        if apply:
            # A full save bumps the scanner version, marks the estimate stale and writes the activity log.
            scanner.sampling_rate = new_rate
            scanner.sampling_mode = SamplingMode.COMPREHENSIVE
            scanner.save(update_fields=["sampling_rate", "sampling_mode", "updated_at"])
    return retired
