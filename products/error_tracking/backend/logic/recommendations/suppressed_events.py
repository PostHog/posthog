import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload

from .fires_on_leave import LastDay, unload_issue_ids
from .impact_lens import (
    MAX_ISSUES,
    WINDOW_HOURS,
    ImpactLens,
    issue_state_join,
    page_path_expr,
    property_expr,
    with_issue_details,
)
from .known_patterns import noise_issue_ids

# The error must fire this soon after the pageview, so the page is the place where it hit people.
EARLY_ERROR_MS = 10000
FOLLOW_MS = 10 * 60 * 1000
MIN_ISSUE_SESSIONS = 60
MIN_COMPARISON_SESSIONS = 200
MAX_TARGETS_PER_TEAM = 10
MIN_EVENT_SHARE = 0.03
MAX_SHARE_RATIO = 0.5
MIN_Z = 5.0
MAX_EVENTS_PER_ISSUE = 3

ISSUE_GROUP = "issue"
COMPARISON_GROUP = "comparison"
TOTAL = "__total"

# Structural and high-volume events that say nothing about what a person went on to do.
EXCLUDED_EVENTS = (
    "$exception",
    "$feature_flag_called",
    "$web_vitals",
    "$set",
    "$groupidentify",
    "$identify",
    "$opt_in",
    "$pageview",
    "$pageleave",
    "$autocapture",
    "$rageclick",
    "$dead_click",
)

# Per issue, the page where it most often fires soon after the pageview.
TARGETS_QUERY = """
    SELECT
        team_id,
        issue_id,
        argMax(path, early_sessions) AS target_path,
        max(early_sessions) AS target_sessions,
        (team_id, issue_id) IN %(noise_issues)s AS is_noise
    FROM (
        SELECT team_id, issue_id, last_pageview_path AS path, uniqExact(session_id) AS early_sessions
        FROM (
            SELECT
                team_id,
                session_id,
                kind,
                ts,
                issue_id,
                maxIf(ts, kind = 'pageview') OVER session_so_far AS last_pageview_ts,
                argMaxIf(path, ts, kind = 'pageview') OVER session_so_far AS last_pageview_path
            FROM (
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    'pageview' AS kind,
                    toUnixTimestamp64Milli(events.timestamp) AS ts,
                    {path} AS path,
                    '' AS issue_id
                FROM events
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$pageview'
                    AND events.timestamp >= %(window_start)s
                    AND events.`$session_id` != ''
                    AND events.`$session_id` IN (
                        SELECT events.`$session_id`
                        FROM events
                        WHERE events.team_id IN %(team_ids)s
                            AND events.event = '$exception'
                            AND events.timestamp >= %(window_start)s
                            AND events.`$session_id` != ''
                    )
                UNION ALL
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    'exception' AS kind,
                    toUnixTimestamp64Milli(events.timestamp) AS ts,
                    '' AS path,
                    toString(issue_state.issue_id) AS issue_id
                FROM events
                {issue_state_join}
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$exception'
                    AND events.timestamp >= %(window_start)s
                    AND events.`$session_id` != ''
                    AND {lib} = 'web'
                    AND issue_state.issue_status = 'active'
                    -- An error that leaving the page causes is followed by nothing, so it would always look harmful.
                    AND (events.team_id, toString(issue_state.issue_id)) NOT IN %(excluded_issues)s
            )
            WINDOW session_so_far AS (
                PARTITION BY team_id, session_id ORDER BY ts ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
        )
        WHERE kind = 'exception'
            AND last_pageview_path != ''
            AND ts - last_pageview_ts <= %(early_error_ms)s
        GROUP BY team_id, issue_id, path
    )
    GROUP BY team_id, issue_id
    HAVING target_sessions >= %(min_issue_sessions)s
    -- Noise goes last, so it only fills the places the other issues leave, and shows the project had issues to test.
    ORDER BY team_id, is_noise ASC, target_sessions DESC
    LIMIT %(max_targets)s BY team_id
"""

# For each target issue and page: sessions where the issue fired soon after a pageview of that page, and sessions
# that saw the page without the issue, each anchored at a pageview, with the events they sent in the next minutes.
SUPPRESSION_QUERY = """
    SELECT team_id, issue_id, grp, event, count() AS sessions
    FROM (
        SELECT team_id, issue_id, grp, arrayJoin(arrayConcat(['{total}'], events_after)) AS event
        FROM (
            SELECT
                team_id,
                tupleElement(target, 2) AS issue_id,
                arraySort(arrayMap(
                    visit -> tupleElement(visit, 1),
                    arrayFilter(visit -> tupleElement(visit, 2) = tupleElement(target, 3), page_visits)
                )) AS visits,
                indexOf(tupleElement(first_seen, 1), issue_id) AS issue_index,
                if(issue_index > 0, tupleElement(first_seen, 2)[issue_index], toInt64(0)) AS first_seen_ts,
                arrayMax(arrayConcat([toInt64(0)], arrayFilter(visit_ts -> visit_ts <= first_seen_ts, visits))) AS visit_before_ts,
                multiIf(
                    issue_index = 0, '{comparison}',
                    visit_before_ts > 0 AND first_seen_ts - visit_before_ts <= %(early_error_ms)s, '{issue}',
                    ''
                ) AS grp,
                if(
                    grp = '{issue}',
                    visit_before_ts,
                    visits[1 + modulo(cityHash64(session_id), greatest(length(visits), 1))]
                ) AS anchor_ts,
                arrayDistinct(arrayMap(
                    sent -> tupleElement(sent, 2),
                    arrayFilter(
                        sent -> tupleElement(sent, 1) >= anchor_ts AND tupleElement(sent, 1) <= anchor_ts + %(follow_ms)s,
                        session_events
                    )
                )) AS events_after
            FROM (
                SELECT
                    team_id,
                    session_id,
                    groupArrayIf((ts, path), kind = 'pageview') AS page_visits,
                    minMapIf([issue_id], [ts], kind = 'exception') AS first_seen,
                    groupArrayIf((ts, event_name), kind = 'event') AS session_events
                FROM (
                    SELECT
                        events.team_id AS team_id,
                        events.`$session_id` AS session_id,
                        multiIf(events.event = '$pageview', 'pageview', events.event = '$exception', 'exception', 'event') AS kind,
                        toUnixTimestamp64Milli(events.timestamp) AS ts,
                        if(events.event = '$pageview', {path}, '') AS path,
                        if(events.event = '$exception', toString(issue_state.issue_id), '') AS issue_id,
                        events.event AS event_name
                    FROM events
                    {issue_state_join}
                    WHERE events.team_id IN %(team_ids)s
                        AND events.timestamp >= %(window_start)s
                        AND events.`$session_id` != ''
                        AND (
                            (events.event = '$pageview' AND (events.team_id, {path}) IN %(target_pages)s)
                            OR events.event = '$exception'
                            OR events.event NOT IN %(excluded_events)s
                        )
                        AND events.`$session_id` IN (
                            SELECT events.`$session_id`
                            FROM events
                            WHERE events.team_id IN %(team_ids)s
                                AND events.event = '$pageview'
                                AND events.timestamp >= %(window_start)s
                                AND events.`$session_id` != ''
                                AND (events.team_id, {path}) IN %(target_pages)s
                        )
                )
                GROUP BY team_id, session_id
            )
            ARRAY JOIN arrayFilter(candidate -> tupleElement(candidate, 1) = team_id, %(targets)s) AS target
            WHERE length(visits) > 0 AND grp != ''
        )
    )
    GROUP BY team_id, issue_id, grp, event
"""

TargetRow = tuple[int, str, str, int]
SuppressionRow = tuple[int, str, str, str, int]


def _query(template: str, *, left_join: bool) -> str:
    return template.format(
        path=page_path_expr(),
        lib=property_expr("$lib"),
        issue_state_join=issue_state_join("LEFT" if left_join else "INNER"),
        total=TOTAL,
        issue=ISSUE_GROUP,
        comparison=COMPARISON_GROUP,
    )


def evaluable_teams(targets: list[TargetRow], rows: list[SuppressionRow]) -> set[int]:
    """Teams with at least one target page whose sessions send custom events."""
    teams_with_targets = {team_id for team_id, *_ in targets}
    return {
        team_id
        for team_id, _, _, event, _ in rows
        if team_id in teams_with_targets and event != TOTAL and not event.startswith("$")
    }


def find_suppressed_events(targets: list[TargetRow], rows: list[SuppressionRow]) -> dict[int, list[dict[str, Any]]]:
    """Pick the events that people send far less often after the issue fired on a page than after visiting it without.

    ``targets`` are ``(team_id, issue_id, path, sessions)``. ``rows`` are ``(team_id, issue_id, group, event,
    sessions)``, where the event ``__total`` carries the size of each group.
    """
    paths = {(team_id, issue_id): path for team_id, issue_id, path, _ in targets}
    totals: dict[tuple[int, str], dict[str, int]] = defaultdict(dict)
    counts: dict[tuple[int, str], dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for team_id, issue_id, group, event, sessions in rows:
        if event == TOTAL:
            totals[(team_id, issue_id)][group] = sessions
        else:
            counts[(team_id, issue_id)][event][group] = sessions

    result: dict[int, list[dict[str, Any]]] = {}
    for key, groups in totals.items():
        issue_sessions = groups.get(ISSUE_GROUP, 0)
        comparison_sessions = groups.get(COMPARISON_GROUP, 0)
        if key not in paths or issue_sessions < MIN_ISSUE_SESSIONS or comparison_sessions < MIN_COMPARISON_SESSIONS:
            continue
        suppressed: list[dict[str, Any]] = []
        for event, by_group in counts[key].items():
            issue_share = by_group.get(ISSUE_GROUP, 0) / issue_sessions
            comparison_share = by_group.get(COMPARISON_GROUP, 0) / comparison_sessions
            if max(issue_share, comparison_share) < MIN_EVENT_SHARE or issue_share > MAX_SHARE_RATIO * comparison_share:
                continue
            pooled = (by_group.get(ISSUE_GROUP, 0) + by_group.get(COMPARISON_GROUP, 0)) / (
                issue_sessions + comparison_sessions
            )
            standard_error = math.sqrt(pooled * (1 - pooled) * (1 / issue_sessions + 1 / comparison_sessions))
            if standard_error == 0 or (comparison_share - issue_share) / standard_error < MIN_Z:
                continue
            suppressed.append(
                {
                    "event": event,
                    "issue_share": round(issue_share, 4),
                    "comparison_share": round(comparison_share, 4),
                }
            )
        if not suppressed:
            continue
        suppressed.sort(key=lambda e: -(e["comparison_share"] - e["issue_share"]))
        team_id, issue_id = key
        result.setdefault(team_id, []).append(
            {
                "id": issue_id,
                "path": paths[key],
                "sessions": issue_sessions,
                "comparison_sessions": comparison_sessions,
                "events": suppressed[:MAX_EVENTS_PER_ISSUE],
            }
        )
    for team_id, issues in result.items():
        result[team_id] = sorted(
            issues,
            key=lambda i: -(i["events"][0]["comparison_share"] - i["events"][0]["issue_share"]) * i["sessions"],
        )[:MAX_ISSUES]
    return result


class SuppressedEventsRecommendation(ImpactLens):
    type = "suppressed_events"
    refresh_interval = timedelta(hours=6)
    # Reads the same leave timing rows as Fires as people leave, so both go stale together and share them.
    refresh_group = "last_day_unload"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:suppressed_events",
        )
        day = LastDay.before(timezone.now())
        window_start: datetime = day.start
        unload = unload_issue_ids(team_ids, day.start, day.end)
        noise = noise_issue_ids(team_ids)
        candidates = [
            (team_id, str(issue_id), path, sessions, bool(is_noise))
            for team_id, issue_id, path, sessions, is_noise in sync_execute(
                _query(TARGETS_QUERY, left_join=False),
                {
                    "team_ids": team_ids,
                    "window_start": window_start,
                    "early_error_ms": EARLY_ERROR_MS,
                    "min_issue_sessions": MIN_ISSUE_SESSIONS,
                    "max_targets": MAX_TARGETS_PER_TEAM,
                    # A placeholder pair keeps each tuple list non-empty, which ClickHouse needs for IN.
                    "excluded_issues": [(team_id, issue_id) for team_id, ids in unload.items() for issue_id in ids]
                    or [(0, "")],
                    "noise_issues": [(team_id, issue_id) for team_id, ids in noise.items() for issue_id in ids]
                    or [(0, "")],
                },
                workload=Workload.OFFLINE,
            )
        ]
        targets: list[TargetRow] = [
            (team_id, issue_id, path, sessions)
            for team_id, issue_id, path, sessions, is_noise in candidates
            if not is_noise
        ]
        # A project whose issues to test were all noise could run the lens, and nothing was flagged.
        only_noise = {team_id for team_id, *_ in candidates} - {team_id for team_id, *_ in targets}
        rows: list[SuppressionRow] = []
        if targets:
            rows = sync_execute(
                _query(SUPPRESSION_QUERY, left_join=True),
                {
                    "team_ids": sorted({team_id for team_id, *_ in targets}),
                    "window_start": window_start,
                    "early_error_ms": EARLY_ERROR_MS,
                    "follow_ms": FOLLOW_MS,
                    "excluded_events": list(EXCLUDED_EVENTS),
                    "targets": [(team_id, issue_id, path) for team_id, issue_id, path, _ in targets],
                    "target_pages": sorted({(team_id, path) for team_id, _, path, _ in targets}),
                },
                workload=Workload.OFFLINE,
            )
        evaluable = evaluable_teams(targets, rows) | only_noise
        issues = with_issue_details(team_ids, find_suppressed_events(targets, rows))
        return {
            team_id: {"window_hours": WINDOW_HOURS, "evaluable": team_id in evaluable, "issues": issues[team_id]}
            for team_id in team_ids
        }
