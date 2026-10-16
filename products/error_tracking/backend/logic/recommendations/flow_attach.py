import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .fires_on_leave import unload_issue_ids
from .impact_lens import issue_state_join, issue_summaries, page_path_expr, property_expr
from .known_patterns import HARMLESS_PATTERNS, issue_patterns
from .page_flows import BASELINE_DAYS, FINISH_MINUTES, EvaluationWindow, Flow, clickhouse_time

# An error is attached to a drop only when the visits that got it on the start page finished much less often than the
# other visits in the same hour. An error that only spiked in the same hour is linked to a drop no more often than chance.
EXPOSURE_SECONDS = 10
MIN_EXPOSED_VISITS = 20
MAX_EXPOSED_FINISH_RATIO = 0.5
MIN_ATTACH_Z = 4.0
# The gap must also be wider than the issue's usual gap at that hour, because some issues always go with failed visits.
MIN_GAP_OVER_USUAL = 0.15
MIN_ISSUE_DAY_VISITS = 3
# Each attach read window starts an hour before the hour it tests and ends after that hour's finish window.
ATTACH_LOOKBACK_HOURS = 1
ATTACH_WINDOW_MINUTES = (ATTACH_LOOKBACK_HOURS + 1) * 60 + FINISH_MINUTES

# Per incident, issue and day: visits whose first view of the start page falls in the incident's worst hour, or the same
# hour on one of the previous days, and how many of them finished. Issue '' counts all visits. A visit is exposed to an
# issue when the issue fired on the start page in the visit's first seconds. Events are read only in the windows
# around those hours, from an hour before (so the first view of the start page sees the session's earlier views) to
# after the finish window.
ATTACH_QUERY = """
    SELECT team_id, incident_index, days_before, issue_id, count() AS visits, countIf(finished) AS finishes
    FROM (
        SELECT team_id, incident_index, days_before, finished, arrayJoin(arrayConcat([''], exposed_issue_ids)) AS issue_id
        FROM (
            SELECT
                visit_rows.team_id AS team_id,
                visit_rows.incident_index AS incident_index,
                visit_rows.session_id AS session_id,
                visit_rows.days_before AS days_before,
                visit_rows.finished AS finished,
                groupUniqArrayIf(
                    exceptions.issue_id,
                    exceptions.issue_id != ''
                        AND exceptions.path = visit_rows.from_path
                        AND exceptions.ts >= visit_rows.started_at
                        AND exceptions.ts <= visit_rows.started_at + toIntervalSecond(%(exposure_seconds)s)
                ) AS exposed_issue_ids
            FROM (
                SELECT team_id, incident_index, session_id, from_path, started_at, finished, intDiv(hours_before, 24) AS days_before
                FROM (
                    SELECT
                        visits_by_session.team_id AS team_id,
                        visits_by_session.session_id AS session_id,
                        tupleElement(incident, 2) AS incident_index,
                        tupleElement(incident, 4) AS from_path,
                        tupleElement(arrayFirst(visit -> tupleElement(visit, 2) = from_path, visits), 1) AS started_at,
                        tupleElement(
                            arrayFirst(
                                visit -> tupleElement(visit, 2) = tupleElement(incident, 5)
                                    AND tupleElement(visit, 1) > started_at
                                    AND tupleElement(visit, 1) <= started_at + toIntervalMinute(%(finish_minutes)s),
                                visits
                            ),
                            1
                        ) AS finished_at,
                        finished_at > started_at AS finished,
                        dateDiff('hour', toStartOfHour(started_at), toDateTime(tupleElement(incident, 3), 'UTC')) AS hours_before
                    FROM (
                        SELECT team_id, session_id, arraySort(visit -> tupleElement(visit, 1), groupArray((ts, path))) AS visits
                        FROM (
                            SELECT events.team_id AS team_id, events.`$session_id` AS session_id, events.timestamp AS ts, {path} AS path
                            FROM events
                            WHERE events.team_id IN %(team_ids)s
                                AND events.event = '$pageview'
                                AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
                                AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
                                AND events.`$session_id` != ''
                                AND arrayExists(
                                    window_start -> events.timestamp >= window_start
                                        AND events.timestamp < window_start + toIntervalMinute(%(window_minutes)s),
                                    arrayMap(bound -> toDateTime64(bound, 6, 'UTC'), %(windows)s)
                                )
                        )
                        WHERE path IN %(paths)s
                        GROUP BY team_id, session_id
                    ) AS visits_by_session
                    ARRAY JOIN arrayFilter(
                        incident -> tupleElement(incident, 1) = visits_by_session.team_id, %(incidents)s
                    ) AS incident
                    WHERE arrayExists(visit -> tupleElement(visit, 2) = tupleElement(incident, 4), visits)
                )
                WHERE hours_before >= 0
                    AND hours_before <= %(max_hours_before)s
                    AND modulo(hours_before, 24) = 0
                    -- A visit that finished in its first seconds had less time to get an error than the others.
                    AND NOT (finished AND finished_at <= started_at + toIntervalSecond(%(exposure_seconds)s))
            ) AS visit_rows
            LEFT JOIN (
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    events.timestamp AS ts,
                    toString(issue_state.issue_id) AS issue_id,
                    {path} AS path
                FROM events
                {issue_state_join}
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$exception'
                    AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
                    AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
                    AND events.`$session_id` != ''
                    AND {lib} = 'web'
                    AND issue_state.issue_status = 'active'
                    AND {path} IN %(paths)s
                    AND arrayExists(
                        window_start -> events.timestamp >= window_start
                            AND events.timestamp < window_start + toIntervalMinute(%(window_minutes)s),
                        arrayMap(bound -> toDateTime64(bound, 6, 'UTC'), %(windows)s)
                    )
            ) AS exceptions ON exceptions.team_id = visit_rows.team_id AND exceptions.session_id = visit_rows.session_id
            GROUP BY team_id, incident_index, session_id, from_path, started_at, days_before, finished
        )
    )
    GROUP BY team_id, incident_index, days_before, issue_id
    -- The minimum applies to the incident's hour only, so the issue's usual exposure on the previous days stays whole.
    HAVING issue_id = '' OR days_before > 0 OR visits >= %(min_issue_day_visits)s
"""


@frozen
class VisitCounts:
    visits: int
    finishes: int


@frozen
class AttachedIssue:
    issue_id: str
    visits: int
    exposed: int
    exposed_finished: int
    exposed_finish_rate: float
    unexposed_finish_rate: float


@frozen
class AttachTarget:
    """A flow's hour to test: which errors sat in the visits that did not get through."""

    team_id: int
    hour: datetime
    flow: Flow


def find_attached_issues(counts: dict[str, dict[int, VisitCounts]]) -> list[AttachedIssue]:
    """Issues whose visits finished far less often than the other visits in the incident's worst hour.

    ``counts`` maps an issue id to its visits by days before the incident, where 0 is the incident's hour.
    Issue '' holds all visits.
    """
    no_visits = VisitCounts(visits=0, finishes=0)
    all_visits = counts.get("", {})
    total = all_visits.get(0, no_visits)
    usual_visits = sum(day.visits for days, day in all_visits.items() if days > 0)
    usual_finishes = sum(day.finishes for days, day in all_visits.items() if days > 0)
    attached = []
    for issue_id, by_day in counts.items():
        exposed = by_day.get(0, no_visits)
        if issue_id == "" or exposed.visits < MIN_EXPOSED_VISITS or total.visits - exposed.visits < MIN_EXPOSED_VISITS:
            continue
        exposed_rate = exposed.finishes / exposed.visits
        unexposed_rate = (total.finishes - exposed.finishes) / (total.visits - exposed.visits)
        z = (unexposed_rate - exposed_rate) / math.sqrt(
            max(unexposed_rate * (1 - unexposed_rate), 1e-9) / exposed.visits
        )
        if exposed_rate > MAX_EXPOSED_FINISH_RATIO * unexposed_rate or z < MIN_ATTACH_Z:
            continue
        usual_exposed = sum(day.visits for days, day in by_day.items() if days > 0)
        usual_exposed_finished = sum(day.finishes for days, day in by_day.items() if days > 0)
        if usual_exposed >= MIN_EXPOSED_VISITS and usual_visits > usual_exposed:
            usual_gap = (usual_finishes - usual_exposed_finished) / (
                usual_visits - usual_exposed
            ) - usual_exposed_finished / usual_exposed
            if (unexposed_rate - exposed_rate) - usual_gap < MIN_GAP_OVER_USUAL:
                continue
        attached.append(
            AttachedIssue(
                issue_id=issue_id,
                visits=total.visits,
                exposed=exposed.visits,
                exposed_finished=exposed.finishes,
                exposed_finish_rate=round(exposed_rate, 4),
                unexposed_finish_rate=round(unexposed_rate, 4),
            )
        )
    return sorted(attached, key=lambda issue: (-(issue.exposed - issue.exposed_finished), issue.issue_id))


def attach_windows(hours: list[datetime]) -> list[str]:
    """The start of each read window around the tested hours and the same hours on the previous days."""
    starts = {
        hour - timedelta(days=days, hours=ATTACH_LOOKBACK_HOURS) for hour in hours for days in range(BASELINE_DAYS + 1)
    }
    return [clickhouse_time(start) for start in sorted(starts)]


def linked_issues(targets: list[AttachTarget], window: EvaluationWindow) -> list[list[dict[str, Any]]]:
    """For each target, the issues attached to it, with their name, description and status.

    Known harmless patterns and errors that fire as people leave are left out, and so are issues that no longer exist.
    """
    if not targets:
        return []
    team_ids = sorted({target.team_id for target in targets})
    attach_rows = sync_execute(
        ATTACH_QUERY.format(path=page_path_expr(), issue_state_join=issue_state_join(), lib=property_expr("$lib")),
        {
            "team_ids": team_ids,
            "incidents": [
                (target.team_id, index, clickhouse_time(target.hour), target.flow.from_path, target.flow.to_path)
                for index, target in enumerate(targets)
            ],
            "paths": sorted({page for target in targets for page in (target.flow.from_path, target.flow.to_path)}),
            "since": clickhouse_time(window.history_since - timedelta(hours=ATTACH_LOOKBACK_HOURS)),
            "until": clickhouse_time(window.read_until),
            "windows": attach_windows([target.hour for target in targets]),
            "window_minutes": ATTACH_WINDOW_MINUTES,
            "finish_minutes": FINISH_MINUTES,
            "exposure_seconds": EXPOSURE_SECONDS,
            "max_hours_before": BASELINE_DAYS * 24,
            "min_issue_day_visits": MIN_ISSUE_DAY_VISITS,
        },
        workload=Workload.OFFLINE,
    )
    counts_by_target: dict[int, dict[str, dict[int, VisitCounts]]] = defaultdict(lambda: defaultdict(dict))
    for _, target_index, days_before, issue_id, visits, finishes in attach_rows:
        counts_by_target[target_index][issue_id][days_before] = VisitCounts(visits=visits, finishes=finishes)
    attached_by_target = [find_attached_issues(counts_by_target[index]) for index in range(len(targets))]
    issue_ids = sorted({issue.issue_id for attached in attached_by_target for issue in attached})
    if not issue_ids:
        return [[] for _ in targets]

    attached_teams = sorted({target.team_id for target, attached in zip(targets, attached_by_target) if attached})
    # A harmless pattern, such as a cross-origin script error, can sit in failed visits without breaking them.
    patterns = issue_patterns(attached_teams, issue_ids, window.history_since, window.read_until)
    # An error that leaving the page causes sits in visits that did not finish because people left.
    unload = unload_issue_ids(attached_teams, window.first_hour, window.read_until)
    summaries = issue_summaries(attached_teams, issue_ids)
    return [
        [
            {
                **summary,
                "visits": issue.visits,
                "exposed": issue.exposed,
                "exposed_finished": issue.exposed_finished,
                "exposed_finish_rate": issue.exposed_finish_rate,
                "unexposed_finish_rate": issue.unexposed_finish_rate,
            }
            for issue in attached
            if (summary := summaries.get((target.team_id, issue.issue_id))) is not None
            and patterns.get(issue.issue_id) not in HARMLESS_PATTERNS
            and issue.issue_id not in unload.get(target.team_id, set())
        ]
        for target, attached in zip(targets, attached_by_target)
    ]
