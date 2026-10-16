import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .impact_lens import WINDOW_HOURS, page_path_expr, per_team_results

MIN_PAGE_SESSIONS = 100
MIN_TRANSITION_SESSIONS = 40
# A transition almost nobody takes is noise, and one almost everybody takes is a redirect, not a step people complete.
MIN_TRANSITION_RATE = 0.05
MAX_TRANSITION_RATE = 0.95
MAX_FLOWS = 8
MAX_FLOWS_PER_PAGE = 2
# A chain links flows where one flow's second page is the next flow's first page, and never visits a page twice.
MIN_CHAIN_PAGES = 3
MAX_CHAIN_PAGES = 4
MAX_CHAINS = 8
FINISH_MINUTES = 30
BASELINE_DAYS = 7
MIN_STARTS = 200
MIN_BASELINE_STARTS = 30
MIN_BASELINE_DAYS = 4
# A visit that starts late in an hour needs time to finish, so an hour is evaluated only once it is this old.
SETTLE_MINUTES = FINISH_MINUTES + 60
# Many more visits than usual with the usual number of finishes is extra traffic, such as a bot or a campaign, not a
# broken step.
SURGE_STARTS_RATIO = 3.0
SURGE_FINISHES_RATIO = 0.9

# One row per page and per transition between two different pages, over the sessions of the last day.
DISCOVERY_QUERY = """
    SELECT team_id, tupleElement(item, 1) AS kind, tupleElement(item, 2) AS from_path, tupleElement(item, 3) AS to_path,
        count() AS sessions
    FROM (
        SELECT
            team_id,
            arrayJoin(arrayConcat(
                arrayMap(page -> ('page', page, ''), arrayDistinct(paths)),
                arrayDistinct(arrayFilter(
                    transition -> tupleElement(transition, 2) != tupleElement(transition, 3),
                    arrayMap(i -> ('transition', paths[i], paths[i + 1]), range(1, length(paths)))
                ))
            )) AS item
        FROM (
            SELECT
                team_id,
                session_id,
                arrayMap(visit -> tupleElement(visit, 2), arraySort(visit -> tupleElement(visit, 1), groupArray((ts, path)))) AS paths
            FROM (
                SELECT events.team_id AS team_id, events.`$session_id` AS session_id, events.timestamp AS ts, {path} AS path
                FROM events
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$pageview'
                    AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
                    AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
                    AND events.`$session_id` != ''
            )
            GROUP BY team_id, session_id
        )
    )
    GROUP BY team_id, kind, from_path, to_path
    HAVING (kind = 'page' AND sessions >= %(min_page_sessions)s)
        OR (kind = 'transition' AND sessions >= %(min_transition_sessions)s)
    ORDER BY team_id, sessions DESC
    LIMIT 2000 BY team_id
"""

# Per page path and hour: sessions whose first visit to the path's first page falls in the hour, and how many of them
# went on to each next page of the path within FINISH_MINUTES of the page before. A path has 2 to 4 pages.
STEPS_QUERY = """
    SELECT
        team_id,
        path_index,
        toStartOfHour(t1) AS bucket,
        count() AS reached_1,
        countIf(t2 > t1) AS reached_2,
        countIf(length(pages) >= 3 AND t2 > t1 AND t3 > t2) AS reached_3,
        countIf(length(pages) >= 4 AND t2 > t1 AND t3 > t2 AND t4 > t3) AS reached_4
    FROM (
        SELECT
            visits_by_session.team_id AS team_id,
            tupleElement(page_path, 2) AS path_index,
            tupleElement(page_path, 3) AS pages,
            tupleElement(arrayFirst(visit -> tupleElement(visit, 2) = pages[1], visits), 1) AS t1,
            {next_steps}
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
            )
            WHERE path IN %(pages)s
            GROUP BY team_id, session_id
        ) AS visits_by_session
        -- Only the session's own team's paths, so a batch of many teams does not multiply every session.
        ARRAY JOIN arrayFilter(
            page_path -> tupleElement(page_path, 1) = visits_by_session.team_id, %(page_paths)s
        ) AS page_path
        WHERE arrayExists(visit -> tupleElement(visit, 2) = tupleElement(page_path, 3)[1], visits)
    )
    GROUP BY team_id, path_index, bucket
"""

# Each next page counts only when it comes after the page before, within the finish window.
NEXT_STEP = """tupleElement(
                arrayFirst(
                    visit -> tupleElement(visit, 2) = pages[{step}]
                        AND tupleElement(visit, 1) > t{previous}
                        AND tupleElement(visit, 1) <= t{previous} + toIntervalMinute(%(finish_minutes)s),
                    visits
                ),
                1
            ) AS t{step}"""


@frozen
class StepCounts:
    """The visits of one hour that reached each page of a path.

    ``reached[0]`` counts the visits whose first view of the first page falls in the hour, and ``reached[i]`` those that
    went on to page i + 1 within FINISH_MINUTES of the page before.
    """

    reached: tuple[int, ...]

    @property
    def starts(self) -> int:
        return self.reached[0]

    @property
    def finishes(self) -> int:
        return self.reached[-1]


HourlyStats = dict[datetime, StepCounts]


@frozen
class Flow:
    from_path: str
    to_path: str


@frozen
class Chain:
    """Three or four pages that people move through in order, linked from flows."""

    pages: tuple[str, ...]

    @property
    def steps(self) -> list[Flow]:
        return [Flow(from_path=from_path, to_path=to_path) for from_path, to_path in zip(self.pages, self.pages[1:])]


@frozen
class PageFlows:
    """A team's watched flows and chains, each with its hourly step counts."""

    flows: list[Flow]
    flow_hours: list[HourlyStats]
    chains: list[Chain]
    chain_hours: list[HourlyStats]


NO_PAGE_FLOWS = PageFlows(flows=[], flow_hours=[], chains=[], chain_hours=[])


@frozen
class EvaluationWindow:
    """The hours a run evaluates. Each hour must be old enough that visits starting late in it had time to finish."""

    first_hour: datetime
    last_hour: datetime

    @classmethod
    def ending_before(cls, now: datetime) -> "EvaluationWindow":
        last_hour = (now - timedelta(minutes=SETTLE_MINUTES)).replace(minute=0, second=0, microsecond=0)
        return cls(first_hour=last_hour - timedelta(hours=WINDOW_HOURS - 1), last_hour=last_hour)

    @property
    def read_until(self) -> datetime:
        """The end of the pageviews a run reads: the end of the last hour's finish window. It depends only on the
        window, so lenses in one sweep that evaluate the same hours read the same pageviews and can share them."""
        return self.last_hour + timedelta(minutes=SETTLE_MINUTES)

    @property
    def history_since(self) -> datetime:
        return self.first_hour - timedelta(days=BASELINE_DAYS)

    def __contains__(self, hour: datetime) -> bool:
        return self.first_hour <= hour <= self.last_hour


def clickhouse_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def pick_flows(rows: list[tuple[int, str, str, str, int]]) -> dict[int, list[Flow]]:
    """Pick the two-page flows to watch, from ``(team_id, kind, from_path, to_path, sessions)`` rows.

    A ``page`` row counts the sessions that visited a page and a ``transition`` row the sessions that went directly
    from one page to another.
    """
    page_sessions = {(team_id, from_path): sessions for team_id, kind, from_path, _, sessions in rows if kind == "page"}
    candidates: dict[int, list[tuple[int, Flow]]] = defaultdict(list)
    for team_id, kind, from_path, to_path, sessions in rows:
        starts = page_sessions.get((team_id, from_path), 0)
        if kind != "transition" or starts < MIN_PAGE_SESSIONS or sessions < MIN_TRANSITION_SESSIONS:
            continue
        if MIN_TRANSITION_RATE <= sessions / starts <= MAX_TRANSITION_RATE:
            candidates[team_id].append((sessions, Flow(from_path=from_path, to_path=to_path)))

    flows: dict[int, list[Flow]] = {}
    for team_id, transitions in candidates.items():
        picked: list[Flow] = []
        per_page: dict[str, int] = defaultdict(int)
        for _, flow in sorted(transitions, key=lambda t: (-t[0], t[1].from_path, t[1].to_path)):
            reverse = Flow(from_path=flow.to_path, to_path=flow.from_path)
            if per_page[flow.from_path] >= MAX_FLOWS_PER_PAGE or reverse in picked:
                continue
            picked.append(flow)
            per_page[flow.from_path] += 1
            if len(picked) >= MAX_FLOWS:
                break
        flows[team_id] = picked
    return flows


def pick_chains(flows: list[Flow]) -> list[Chain]:
    """Link flows into chains of 3 or 4 pages, where one flow's second page is the next flow's first page.

    A chain that is part of a longer chain is left out, because the longer chain's steps already cover it. Chains come
    in the order of the flows they start with, which is the busiest flow first.
    """
    next_flows: dict[str, list[Flow]] = defaultdict(list)
    for flow in flows:
        next_flows[flow.from_path].append(flow)

    found: list[tuple[str, ...]] = []

    def extend(pages: tuple[str, ...]) -> None:
        if len(pages) >= MIN_CHAIN_PAGES:
            found.append(pages)
        if len(pages) == MAX_CHAIN_PAGES:
            return
        for flow in next_flows[pages[-1]]:
            if flow.to_path not in pages:
                extend((*pages, flow.to_path))

    for flow in flows:
        extend((flow.from_path, flow.to_path))

    def is_part_of(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
        return len(short) < len(long) and any(
            long[start : start + len(short)] == short for start in range(len(long) - len(short) + 1)
        )

    return [Chain(pages=pages) for pages in found if not any(is_part_of(pages, other) for other in found)][:MAX_CHAINS]


def fetch_step_hours(
    page_paths: dict[int, list[tuple[str, ...]]], since: datetime, until: datetime
) -> dict[tuple[int, int], HourlyStats]:
    """The hourly step counts of each team's page paths between ``since`` and ``until``, by team and path index."""
    params = [
        (team_id, index, list(pages)) for team_id, paths in page_paths.items() for index, pages in enumerate(paths)
    ]
    if not params:
        return {}
    rows = sync_execute(
        STEPS_QUERY.format(
            path=page_path_expr(),
            next_steps=",\n            ".join(
                NEXT_STEP.format(step=step, previous=step - 1) for step in range(2, MAX_CHAIN_PAGES + 1)
            ),
        ),
        {
            "team_ids": sorted({team_id for team_id, _, _ in params}),
            "page_paths": params,
            "pages": sorted({page for _, _, pages in params for page in pages}),
            "since": clickhouse_time(since),
            "until": clickhouse_time(until),
            "finish_minutes": FINISH_MINUTES,
        },
        workload=Workload.OFFLINE,
    )
    hours: dict[tuple[int, int], HourlyStats] = defaultdict(dict)
    for team_id, path_index, bucket, *reached in rows:
        length = len(page_paths[team_id][path_index])
        hours[(team_id, path_index)][_as_utc(bucket)] = StepCounts(reached=tuple(reached[:length]))
    return hours


def fetch_page_flows(team_ids: list[int], window: EvaluationWindow) -> dict[int, PageFlows]:
    """Each team's watched flows and chains with their hourly step counts. Within one sweep batch, each team's pageviews
    are read once for both lenses that watch them."""
    return per_team_results(
        ("page_flows", window.last_hour),
        team_ids,
        lambda missing: _query_page_flows(missing, window),
        lambda: NO_PAGE_FLOWS,
    )


def _query_page_flows(team_ids: list[int], window: EvaluationWindow) -> dict[int, PageFlows]:
    discovery_rows = sync_execute(
        DISCOVERY_QUERY.format(path=page_path_expr()),
        {
            "team_ids": team_ids,
            "since": clickhouse_time(window.read_until - timedelta(hours=WINDOW_HOURS)),
            "until": clickhouse_time(window.read_until),
            "min_page_sessions": MIN_PAGE_SESSIONS,
            "min_transition_sessions": MIN_TRANSITION_SESSIONS,
        },
        workload=Workload.OFFLINE,
    )
    flows = pick_flows(discovery_rows)
    chains = {team_id: pick_chains(team_flows) for team_id, team_flows in flows.items()}
    # Flows come first in each team's paths, then chains, so a path index tells them apart.
    page_paths = {
        team_id: [(flow.from_path, flow.to_path) for flow in team_flows] + [chain.pages for chain in chains[team_id]]
        for team_id, team_flows in flows.items()
        if team_flows
    }
    hours = fetch_step_hours(page_paths, window.history_since, window.read_until)
    return {
        team_id: PageFlows(
            flows=team_flows,
            flow_hours=[hours.get((team_id, index), {}) for index in range(len(team_flows))],
            chains=chains[team_id],
            chain_hours=[hours.get((team_id, len(team_flows) + index), {}) for index in range(len(chains[team_id]))],
        )
        for team_id, team_flows in flows.items()
    }


def is_evaluable(hours: HourlyStats, window: EvaluationWindow) -> bool:
    """Whether any hour in the window had enough visits to judge a drop."""
    return any(hour in window and counts.starts >= MIN_STARTS for hour, counts in hours.items())


@frozen
class Baseline:
    """The median of the same hour on the previous days, over the days with enough starts."""

    rate: float
    starts: float
    finishes: float


def baseline_days(
    hours: HourlyStats, hour: datetime, enough: int = MIN_BASELINE_STARTS, step: int = 0
) -> list[StepCounts]:
    """The same hour on each previous day where at least ``enough`` visits reached page ``step`` of the path."""
    days = (hours.get(hour - timedelta(days=days)) for days in range(1, BASELINE_DAYS + 1))
    return [counts for counts in days if counts is not None and counts.reached[step] >= enough]


def baseline(hours: HourlyStats, hour: datetime) -> Baseline | None:
    """The usual rate, starts and finishes of ``hour``, or None without enough previous days."""
    days = baseline_days(hours, hour)
    if len(days) < MIN_BASELINE_DAYS:
        return None
    return Baseline(
        rate=statistics.median(counts.finishes / counts.starts for counts in days),
        starts=statistics.median(counts.starts for counts in days),
        finishes=statistics.median(counts.finishes for counts in days),
    )


def usual(hours: HourlyStats, hour: datetime) -> Baseline:
    """The baseline of a drop hour. Drop hours only come from rules that skip hours without a baseline."""
    found = baseline(hours, hour)
    assert found is not None
    return found


def merge_drop_hours(drop_hours: list[datetime]) -> list[list[datetime]]:
    """Group consecutive drop hours into incidents."""
    incidents: list[list[datetime]] = []
    for hour in sorted(drop_hours):
        if incidents and hour - incidents[-1][-1] <= timedelta(hours=1):
            incidents[-1].append(hour)
        else:
            incidents.append([hour])
    return incidents


def is_surge(hours: HourlyStats, drop: list[datetime]) -> bool:
    """Whether the incident's busiest hour, against normal, had extra visits and the usual number of finishes."""
    peak = max(drop, key=lambda hour: hours[hour].starts / usual(hours, hour).starts)
    peak_usual = usual(hours, peak)
    finishes_ratio = hours[peak].finishes / peak_usual.finishes if peak_usual.finishes > 0 else math.inf
    return hours[peak].starts / peak_usual.starts >= SURGE_STARTS_RATIO and finishes_ratio >= SURGE_FINISHES_RATIO


def worst_hour(hours: HourlyStats, drop: list[datetime]) -> datetime:
    """The incident's hour with the lowest rate against its usual rate."""

    def relative_rate(hour: datetime) -> float:
        hour_usual = usual(hours, hour)
        return hours[hour].finishes / hours[hour].starts / hour_usual.rate if hour_usual.rate > 0 else 1.0

    return min(drop, key=relative_rate)


def hourly_series(hours: HourlyStats, window: EvaluationWindow) -> list[dict[str, Any]]:
    series = []
    for offset in range(WINDOW_HOURS):
        hour = window.first_hour + timedelta(hours=offset)
        counts = hours.get(hour)
        hour_usual = baseline(hours, hour)
        series.append(
            {
                "hour": hour.isoformat(),
                "starts": counts.starts if counts else 0,
                "rate": round(counts.finishes / counts.starts, 4) if counts and counts.starts else None,
                "usual_rate": round(hour_usual.rate, 4) if hour_usual is not None else None,
            }
        )
    return series


def incident_counts(hours: HourlyStats, drop: list[datetime], window: EvaluationWindow) -> dict[str, Any]:
    """The incident's worst hour's starts and finishes next to their usual values, and the hourly series to draw."""
    worst = worst_hour(hours, drop)
    counts = hours[worst]
    worst_usual = usual(hours, worst)
    return {
        "hour": drop[0].isoformat(),
        "hours": len(drop),
        "worst_hour": worst.isoformat(),
        "starts": counts.starts,
        "finishes": counts.finishes,
        "rate": round(counts.finishes / counts.starts, 4),
        "usual_starts": round(worst_usual.starts, 1),
        "usual_finishes": round(worst_usual.finishes, 1),
        "usual_rate": round(worst_usual.rate, 4),
        "hourly": hourly_series(hours, window),
    }
