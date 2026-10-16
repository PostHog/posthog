import math
from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .impact_lens import MAX_ISSUES, WINDOW_HOURS, ImpactLens, issue_state_join, with_issue_details

MIN_SESSIONS = 40
HEAVY_SESSION_OCCURRENCES = 50
REPEATING_SESSION_OCCURRENCES = 5
MIN_TOP_SESSION_SHARE = 0.2
MIN_HEAVY_SESSION_SHARE = 0.3
MIN_REPEATING_SESSIONS = 10
MIN_TIMER_SHARE = 0.2

ISSUE_QUERY = """
    SELECT
        team_id,
        issue_id,
        count() AS sessions,
        sum(occurrences) AS total_occurrences,
        max(occurrences) AS top_session_occurrences,
        sumIf(occurrences, occurrences >= %(heavy_session_occurrences)s) AS heavy_session_occurrences,
        countIf(occurrences >= %(repeating_session_occurrences)s) AS repeating_sessions,
        countIf(occurrences >= %(repeating_session_occurrences)s AND on_timer) AS timer_sessions,
        quantileIf(0.5)(median_gap_ms, occurrences >= %(repeating_session_occurrences)s AND on_timer) AS timer_gap_ms
    FROM (
        SELECT
            events.team_id AS team_id,
            issue_state.issue_id AS issue_id,
            events.`$session_id` AS session_id,
            count() AS occurrences,
            arrayPopFront(arrayDifference(arraySort(groupArray(toUnixTimestamp64Milli(events.timestamp))))) AS gaps,
            if(length(gaps) > 0, arrayReduce('median', gaps), 0) AS median_gap_ms,
            -- A session is on a timer when most gaps between its occurrences are within a tenth of the median gap.
            length(gaps) >= 4
                AND median_gap_ms >= 1000
                AND arrayAvg(gap -> abs(gap - median_gap_ms) <= 0.1 * median_gap_ms, gaps) >= 0.6 AS on_timer
        FROM events
        {issue_state_join}
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= now() - toIntervalHour(%(window_hours)s)
            AND events.`$session_id` != ''
            AND issue_state.issue_status = 'active'
        GROUP BY team_id, issue_id, session_id
    )
    GROUP BY team_id, issue_id
    HAVING sessions >= %(min_sessions)s
"""


@frozen
class RepetitionRow:
    """How one issue's occurrences spread over its sessions. ``timer_gap_ms`` is NaN without timer sessions."""

    team_id: int
    issue_id: str
    sessions: int
    occurrences: int
    top_session_occurrences: int
    heavy_session_occurrences: int
    repeating_sessions: int
    timer_sessions: int
    timer_gap_ms: float


def find_inflated_counts(rows: list[RepetitionRow]) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues whose occurrence count comes mostly from a few sessions."""
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row.sessions < MIN_SESSIONS or row.occurrences == 0:
            continue
        top_share = row.top_session_occurrences / row.occurrences
        heavy_share = row.heavy_session_occurrences / row.occurrences
        on_timer = (
            row.repeating_sessions >= MIN_REPEATING_SESSIONS
            and row.timer_sessions >= MIN_TIMER_SHARE * row.repeating_sessions
            and not math.isnan(row.timer_gap_ms)
        )
        reasons = [
            reason
            for reason, applies in (
                ("top_session", top_share >= MIN_TOP_SESSION_SHARE),
                ("heavy_sessions", heavy_share >= MIN_HEAVY_SESSION_SHARE),
                ("timer", on_timer),
            )
            if applies
        ]
        if not reasons:
            continue
        result.setdefault(row.team_id, []).append(
            {
                "id": row.issue_id,
                "occurrences": row.occurrences,
                "sessions": row.sessions,
                "top_session_share": round(top_share, 4),
                "heavy_session_share": round(heavy_share, 4),
                "repeating_sessions": row.repeating_sessions,
                "timer_sessions": row.timer_sessions if on_timer else 0,
                "timer_interval_seconds": round(row.timer_gap_ms / 1000) if on_timer else None,
                "reasons": reasons,
            }
        )
    for team_id, issues in result.items():
        result[team_id] = sorted(issues, key=lambda i: -i["occurrences"])[:MAX_ISSUES]
    return result


class InflatedCountsRecommendation(ImpactLens):
    type = "inflated_counts"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:inflated_counts",
        )
        rows = [
            RepetitionRow(
                team_id=team_id,
                issue_id=str(issue_id),
                sessions=sessions,
                occurrences=occurrences,
                top_session_occurrences=top,
                heavy_session_occurrences=heavy,
                repeating_sessions=repeating,
                timer_sessions=timer_sessions,
                timer_gap_ms=timer_gap_ms,
            )
            for team_id, issue_id, sessions, occurrences, top, heavy, repeating, timer_sessions, timer_gap_ms in sync_execute(
                ISSUE_QUERY.format(issue_state_join=issue_state_join()),
                {
                    "team_ids": team_ids,
                    "window_hours": WINDOW_HOURS,
                    "min_sessions": MIN_SESSIONS,
                    "heavy_session_occurrences": HEAVY_SESSION_OCCURRENCES,
                    "repeating_session_occurrences": REPEATING_SESSION_OCCURRENCES,
                },
                workload=Workload.OFFLINE,
            )
        ]
        issues = with_issue_details(team_ids, find_inflated_counts(rows))
        # Only issues with enough sessions come back, so a team without any has nothing this lens can measure.
        evaluable = {row.team_id for row in rows}
        return {
            team_id: {"window_hours": WINDOW_HOURS, "evaluable": team_id in evaluable, "issues": issues[team_id]}
            for team_id in team_ids
        }
