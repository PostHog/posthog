from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .impact_lens import (
    MAX_ISSUES,
    WINDOW_HOURS,
    ImpactLens,
    issue_state_join,
    per_team_results,
    property_expr,
    with_issue_details,
)

# A pageleave this long before or after the error counts as the page being left as the error fired.
LEAVE_BEFORE_MS = 1000
LEAVE_AFTER_MS = 2000
TRIGGER_MS = 2000
BACKGROUND_MS = 30000
# Random moments in this share of sessions measure how often a pageleave lands near any moment at all.
BASELINE_SAMPLE_MODULO = 4
MIN_BASELINE_MOMENTS = 30
MIN_SESSIONS = 40
MIN_LIFT = 2.0
MIN_LEAVE_SHARE = 0.1

BASELINE_CLICK = "__baseline_click"
BASELINE_PAGEVIEW = "__baseline_pageview"
BASELINE_LABELS = (BASELINE_CLICK, BASELINE_PAGEVIEW)
# Counts the sessions that sent a pageleave, so a team without pageleave events is not evaluated.
PAGELEAVE_SESSIONS = "__pageleave_sessions"

QUERY = """
    SELECT
        team_id,
        tupleElement(anchor, 1) AS label,
        count() AS sessions,
        countIf(arrayExists(
            mark -> tupleElement(mark, 2) = 'pageleave'
                AND tupleElement(mark, 1) >= tupleElement(anchor, 2) - %(leave_before_ms)s
                AND tupleElement(mark, 1) <= tupleElement(anchor, 2) + %(leave_after_ms)s,
            marks
        )) AS leave_sessions,
        countIf(arrayExists(
            mark -> tupleElement(mark, 2) = 'pageview'
                AND tupleElement(mark, 1) >= tupleElement(anchor, 2) - %(trigger_ms)s
                AND tupleElement(mark, 1) <= tupleElement(anchor, 2),
            marks
        )) AS navigation_sessions,
        countIf(arrayExists(
            mark -> tupleElement(mark, 2) IN ('click', 'action')
                AND tupleElement(mark, 1) >= tupleElement(anchor, 2) - %(trigger_ms)s
                AND tupleElement(mark, 1) <= tupleElement(anchor, 2),
            marks
        )) AS action_sessions,
        countIf(NOT arrayExists(
            mark -> tupleElement(mark, 2) IN ('pageview', 'click', 'action', 'autocapture')
                AND tupleElement(mark, 1) >= tupleElement(anchor, 2) - %(background_ms)s
                AND tupleElement(mark, 1) < tupleElement(anchor, 2),
            marks
        )) AS background_sessions
    FROM (
        SELECT
            team_id,
            marks,
            arrayJoin(arrayConcat(
                -- Each issue's first occurrence in the session, once there is enough history before it.
                arrayFilter(
                    anchor -> tupleElement(anchor, 2) >= %(window_start_ms)s + %(background_ms)s,
                    arrayMap(
                        (seen_issue, seen_ts) -> (seen_issue, seen_ts),
                        tupleElement(first_seen, 1),
                        tupleElement(first_seen, 2)
                    )
                ),
                if(sampled AND click_count > 0, [('{baseline_click}', random_click_ts)], []),
                if(sampled AND pageview_count > 0, [('{baseline_pageview}', random_pageview_ts + 1000)], []),
                if(pageleave_count > 0, [('{pageleave_sessions}', toInt64(0))], [])
            )) AS anchor
        FROM (
            SELECT
                team_id,
                session_id,
                modulo(cityHash64(session_id), %(baseline_sample_modulo)s) = 0 AS sampled,
                groupArrayIf((ts, kind), kind != 'exception') AS marks,
                minMapIf([issue_id], [ts], kind = 'exception' AND issue_id != '') AS first_seen,
                argMinIf(ts, cityHash64(event_uuid), kind = 'click') AS random_click_ts,
                countIf(kind = 'click') AS click_count,
                argMinIf(ts, cityHash64(event_uuid), kind = 'pageview') AS random_pageview_ts,
                countIf(kind = 'pageview') AS pageview_count,
                countIf(kind = 'pageleave') AS pageleave_count
            FROM (
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    events.uuid AS event_uuid,
                    toUnixTimestamp64Milli(events.timestamp) AS ts,
                    multiIf(
                        events.event = '$pageview', 'pageview',
                        events.event = '$pageleave', 'pageleave',
                        {event_type} = 'click', 'click',
                        {event_type} IN ('submit', 'change'), 'action',
                        'autocapture'
                    ) AS kind,
                    '' AS issue_id
                FROM events
                WHERE events.team_id IN %(team_ids)s
                    AND events.event IN ('$pageview', '$pageleave', '$autocapture')
                    AND events.timestamp >= %(window_start)s
                    AND events.timestamp < %(window_end)s
                    AND events.`$session_id` != ''
                    AND (
                        events.`$session_id` IN (
                            SELECT events.`$session_id`
                            FROM events
                            WHERE events.team_id IN %(team_ids)s
                                AND events.event = '$exception'
                                AND events.timestamp >= %(window_start)s
                                AND events.timestamp < %(window_end)s
                                AND events.`$session_id` != ''
                                AND {lib} = 'web'
                        )
                        OR modulo(cityHash64(events.`$session_id`), %(baseline_sample_modulo)s) = 0
                    )
                UNION ALL
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    events.uuid AS event_uuid,
                    toUnixTimestamp64Milli(events.timestamp) AS ts,
                    'exception' AS kind,
                    toString(issue_state.issue_id) AS issue_id
                FROM events
                {issue_state_join}
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$exception'
                    AND events.timestamp >= %(window_start)s
                    AND events.timestamp < %(window_end)s
                    AND events.`$session_id` != ''
                    AND {lib} = 'web'
                    AND issue_state.issue_status = 'active'
            )
            GROUP BY team_id, session_id
        )
    )
    GROUP BY team_id, label
"""


@frozen
class LeaveRow:
    """One label's sessions in the window. A label is an issue id, a baseline kind, or the pageleave session count."""

    team_id: int
    label: str
    sessions: int
    leave_sessions: int
    navigation_sessions: int
    action_sessions: int
    background_sessions: int


@frozen
class LastDay:
    """The 24 hours a run reads, ending on a whole hour so lenses in one sweep read the same window and share it."""

    start: datetime
    end: datetime

    @classmethod
    def before(cls, now: datetime) -> "LastDay":
        end = now.replace(minute=0, second=0, microsecond=0)
        return cls(start=end - timedelta(hours=WINDOW_HOURS), end=end)


def _query() -> str:
    return QUERY.format(
        baseline_click=BASELINE_CLICK,
        baseline_pageview=BASELINE_PAGEVIEW,
        pageleave_sessions=PAGELEAVE_SESSIONS,
        event_type=property_expr("$event_type"),
        lib=property_expr("$lib"),
        issue_state_join=issue_state_join(),
    )


def baseline_leave_shares(rows: list[LeaveRow]) -> dict[int, float]:
    """How often a pageleave lands near a random click or pageview, per team."""
    shares: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        if row.label in BASELINE_LABELS and row.sessions >= MIN_BASELINE_MOMENTS:
            shares[row.team_id].append(row.leave_sessions / row.sessions)
    return {team_id: sum(values) / len(values) for team_id, values in shares.items()}


def evaluable_teams(rows: list[LeaveRow], baselines: dict[int, float]) -> set[int]:
    """Teams that send pageleave events and have enough random moments to compare against."""
    return {
        row.team_id for row in rows if row.label == PAGELEAVE_SESSIONS and row.sessions > 0 and row.team_id in baselines
    }


def find_fires_on_leave(rows: list[LeaveRow], baselines: dict[int, float]) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues whose first occurrence lands next to a pageleave far more often than a random moment does."""
    return {
        team_id: sorted(issues, key=lambda i: -i["sessions"] * i["leave_share"])[:MAX_ISSUES]
        for team_id, issues in _fires_on_leave(rows, baselines).items()
    }


def _fires_on_leave(rows: list[LeaveRow], baselines: dict[int, float]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        baseline = baselines.get(row.team_id)
        if row.label.startswith("__") or baseline is None or row.sessions < MIN_SESSIONS:
            continue
        leave_share = row.leave_sessions / row.sessions
        if leave_share < MIN_LEAVE_SHARE or leave_share < MIN_LIFT * baseline:
            continue
        result.setdefault(row.team_id, []).append(
            {
                "id": row.label,
                "sessions": row.sessions,
                "leave_share": round(leave_share, 4),
                "baseline_leave_share": round(baseline, 4),
                "after_navigation_share": round(row.navigation_sessions / row.sessions, 4),
                "after_action_share": round(row.action_sessions / row.sessions, 4),
                "background_share": round(row.background_sessions / row.sessions, 4),
            }
        )
    return result


def _query_rows(team_ids: list[int], window_start: datetime, window_end: datetime) -> dict[int, list[LeaveRow]]:
    by_team: dict[int, list[LeaveRow]] = defaultdict(list)
    for team_id, label, sessions, leave, navigation, action, background in sync_execute(
        _query(),
        {
            "team_ids": team_ids,
            "window_start": window_start,
            "window_end": window_end,
            "window_start_ms": int(window_start.timestamp() * 1000),
            "leave_before_ms": LEAVE_BEFORE_MS,
            "leave_after_ms": LEAVE_AFTER_MS,
            "trigger_ms": TRIGGER_MS,
            "background_ms": BACKGROUND_MS,
            "baseline_sample_modulo": BASELINE_SAMPLE_MODULO,
        },
        workload=Workload.OFFLINE,
    ):
        by_team[team_id].append(
            LeaveRow(
                team_id=team_id,
                label=label,
                sessions=sessions,
                leave_sessions=leave,
                navigation_sessions=navigation,
                action_sessions=action,
                background_sessions=background,
            )
        )
    return by_team


def fetch_rows(team_ids: list[int], window_start: datetime, window_end: datetime) -> list[LeaveRow]:
    """The leave timing rows of every team. Within one sweep batch, each team and window is queried once."""
    by_team = per_team_results(
        ("fires_on_leave", window_start, window_end),
        team_ids,
        lambda missing: _query_rows(missing, window_start, window_end),
        list,
    )
    return [row for team_id in team_ids for row in by_team[team_id]]


def unload_issue_ids(team_ids: list[int], window_start: datetime, window_end: datetime) -> dict[int, set[str]]:
    """Every issue that fires as people leave the page, for lenses that must not mistake leaving for harm."""
    rows = fetch_rows(team_ids, window_start, window_end)
    return {
        team_id: {issue["id"] for issue in issues}
        for team_id, issues in _fires_on_leave(rows, baseline_leave_shares(rows)).items()
    }


class FiresOnLeaveRecommendation(ImpactLens):
    type = "fires_on_leave"
    refresh_interval = timedelta(hours=6)
    # Stops next steps reads the same rows to leave these issues out, so both go stale together and share them.
    refresh_group = "last_day_unload"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:fires_on_leave",
        )
        day = LastDay.before(timezone.now())
        rows = fetch_rows(team_ids, day.start, day.end)
        baselines = baseline_leave_shares(rows)
        evaluable = evaluable_teams(rows, baselines)
        issues = with_issue_details(team_ids, find_fires_on_leave(rows, baselines))
        return {
            team_id: {
                "window_hours": WINDOW_HOURS,
                "evaluable": team_id in evaluable,
                "baseline_leave_share": round(baselines.get(team_id, 0.0), 4),
                "issues": issues[team_id],
            }
            for team_id in team_ids
        }
