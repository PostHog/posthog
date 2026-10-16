import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .fires_on_leave import unload_issue_ids
from .impact_lens import issue_state_join, page_path_expr, per_team_results, property_expr
from .known_patterns import noise_issue_ids

# Only errors in the first seconds of a pageview count, so that the error can come before the decision to leave.
EARLY_ERROR_MS = 3000
# Both groups must stay this long, so that pageviews that end before an error can fire do not bias the comparison.
MIN_PAGE_SECONDS = 3
QUICK_LEAVE_SECONDS = 10
RETURN_HOURS = 24
MIN_CONTROL_PAGEVIEWS = 30
MIN_PAGEVIEWS = 50
MIN_LIFT = 1.5
MIN_Z = 4.0
# Fake errors on a random share of pageviews measure the bias of the comparison. They must show no effect.
FAKE_PERCENTS = (3, 10)
MIN_FAKE_PAGEVIEWS = 500
MAX_EXPECTED_SHARE = 0.98
# Each comparison rate is smoothed toward one half by this many pageviews on each side, (count + 0.5) / (pageviews + 1),
# so a comparison group with no leaves at all still gives a finite expectation instead of hiding the issue.
COMPARISON_PRIOR = 0.5
# One day alone flags noise, so a finding must hold on two days a week apart. Each day ends at least a day ago, so
# that every visitor had a full day to come back.
DAYS_AGO = (1, 8)
# Bounds the return lookup for people with very many sessions, such as crawlers.
MAX_PERSON_SESSIONS = 1000

CONTROL = "__control"
FAKE_PREFIX = "__fake_"

# Visitors are compared with visitors of the same kind: crawlers, in-app browsers and webviews leave pages differently.
UA_CLASS = r"""multiIf(
    match(lower({ua}), 'bot|crawl|spider|slurp|headless|lighthouse|python|curl|wget|phantom|selenium|puppeteer|playwright'), 'bot',
    match({ua}, 'FBAN|FBAV|Instagram|Line/|Snapchat|Pinterest|TikTok|musical_ly|Twitter|LinkedInApp|GSA/'), 'inapp',
    match({ua}, '; wv[)]|WebView'), 'webview',
    'regular'
)"""

# Per team, day and label, the matched counts of three measures. A label is an issue id, the comparison group of
# error-free pageviews, or a fake issue. Each issue pageview is compared with error-free pageviews of the same page by
# the same kind of visitor, and a key counts only with enough comparison pageviews.
# - quick: pageviews of known length that ended within 10 seconds after the first 3
# - returned: of those quick leaves, the ones whose person had another session within a day
# - lost: pageviews that ended the session, with no other session by the person within a day
QUERY = """
    SELECT
        team_id,
        day_index,
        label,
        sumIf(timed, control_timed >= %(min_control_pageviews)s) AS matched_timed,
        sumIf(quick, control_timed >= %(min_control_pageviews)s) AS matched_quick,
        sumIf(
            timed * (control_quick + %(prior)s) / (control_timed + 2 * %(prior)s),
            control_timed >= %(min_control_pageviews)s
        ) AS expected_quick,
        sumIf(quick, control_quick >= %(min_control_pageviews)s) AS matched_quick_leaves,
        sumIf(quick_returned, control_quick >= %(min_control_pageviews)s) AS matched_returned,
        sumIf(
            quick * (control_returned + %(prior)s) / (control_quick + 2 * %(prior)s),
            control_quick >= %(min_control_pageviews)s
        ) AS expected_returned,
        sumIf(all_pageviews, control_all >= %(min_control_pageviews)s) AS matched_all,
        sumIf(lost, control_all >= %(min_control_pageviews)s) AS matched_lost,
        sumIf(
            all_pageviews * (control_lost + %(prior)s) / (control_all + 2 * %(prior)s),
            control_all >= %(min_control_pageviews)s
        ) AS expected_lost
    FROM (
        SELECT
            team_id,
            day_index,
            label,
            audience_key,
            timed,
            quick,
            quick_returned,
            all_pageviews,
            lost,
            max(if(label = '{control}', timed, 0)) OVER (PARTITION BY team_id, day_index, audience_key) AS control_timed,
            max(if(label = '{control}', quick, 0)) OVER (PARTITION BY team_id, day_index, audience_key) AS control_quick,
            max(if(label = '{control}', quick_returned, 0)) OVER (PARTITION BY team_id, day_index, audience_key) AS control_returned,
            max(if(label = '{control}', all_pageviews, 0)) OVER (PARTITION BY team_id, day_index, audience_key) AS control_all,
            max(if(label = '{control}', lost, 0)) OVER (PARTITION BY team_id, day_index, audience_key) AS control_lost
        FROM (
            SELECT
                team_id,
                day_index,
                label,
                audience_key,
                countIf(duration >= %(min_page_seconds)s) AS timed,
                countIf(duration >= %(min_page_seconds)s AND duration < %(quick_leave_before_seconds)s) AS quick,
                countIf(
                    duration >= %(min_page_seconds)s AND duration < %(quick_leave_before_seconds)s AND returned
                ) AS quick_returned,
                count() AS all_pageviews,
                countIf(is_exit AND NOT returned) AS lost
            FROM (
                SELECT
                    pageviews.team_id AS team_id,
                    pageviews.day_index AS day_index,
                    pageviews.pageview_audience_key AS audience_key,
                    pageviews.duration AS duration,
                    pageviews.is_exit AS is_exit,
                    arrayExists(
                        visit -> tupleElement(visit, 1) != pageviews.session_id
                            AND tupleElement(visit, 3) > pageviews.pageview_ts
                            AND tupleElement(visit, 2) <= pageviews.pageview_ts + toIntervalHour(%(return_hours)s),
                        returns.sessions
                    ) AS returned,
                    arrayJoin(arrayConcat(
                        if(pageviews.has_exception, pageviews.early_issue_ids, ['{control}']),
                        {fake_labels}
                    )) AS label
                FROM (
                    SELECT
                        team_id,
                        session_id,
                        window_id,
                        pageview_ts,
                        if(pageview_ts >= toDateTime64(%(day0_start)s, 6, 'UTC'), 0, 1) AS day_index,
                        anyIf(audience_key, kind = 'pageview') AS pageview_audience_key,
                        anyIf(person_id, kind = 'pageview') AS pageview_person_id,
                        anyIf(page_duration, kind = 'pageview') AS duration,
                        anyIf(is_last_pageview, kind = 'pageview') AS is_exit,
                        countIf(kind = 'exception') > 0 AS has_exception,
                        groupUniqArrayIf(
                            issue_id,
                            kind = 'exception'
                                AND issue_id != ''
                                AND dateDiff('millisecond', pageview_ts, ts) <= %(early_error_ms)s
                        ) AS early_issue_ids,
                        countIf(kind = 'pageview') AS pageview_rows
                    FROM (
                        SELECT
                            team_id,
                            session_id,
                            window_id,
                            kind,
                            ts,
                            audience_key,
                            person_id,
                            issue_id,
                            if(kind = 'pageview', ts, last_pageview_ts) AS pageview_ts,
                            if(
                                kind = 'pageview' AND next_page_event_ts > ts,
                                dateDiff('millisecond', ts, next_page_event_ts) / 1000,
                                NULL
                            ) AS page_duration,
                            kind = 'pageview' AND ts = session_last_pageview_ts AS is_last_pageview
                        FROM (
                            SELECT
                                *,
                                maxIf(ts, kind = 'pageview') OVER (
                                    PARTITION BY team_id, session_id, window_id
                                    ORDER BY ts ASC
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                                ) AS last_pageview_ts,
                                minIf(ts, kind != 'exception') OVER (
                                    PARTITION BY team_id, session_id, window_id
                                    ORDER BY ts DESC
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                ) AS next_page_event_ts,
                                maxIf(ts, kind = 'pageview') OVER (PARTITION BY team_id, session_id) AS session_last_pageview_ts
                            FROM (
                                SELECT
                                    events.team_id AS team_id,
                                    events.`$session_id` AS session_id,
                                    {window_id} AS window_id,
                                    if(events.event = '$pageview', 'pageview', 'pageleave') AS kind,
                                    events.timestamp AS ts,
                                    concat({path}, '|', {browser}, '|', {device_type}, '|', {ua_class}) AS audience_key,
                                    events.person_id AS person_id,
                                    '' AS issue_id
                                FROM events
                                WHERE events.team_id IN %(team_ids)s
                                    AND events.event IN ('$pageview', '$pageleave')
                                    AND {in_days}
                                    AND events.`$session_id` != ''
                                UNION ALL
                                SELECT
                                    events.team_id AS team_id,
                                    events.`$session_id` AS session_id,
                                    {window_id} AS window_id,
                                    'exception' AS kind,
                                    events.timestamp AS ts,
                                    '' AS audience_key,
                                    events.person_id AS person_id,
                                    if(issue_state.issue_status = 'active', toString(issue_state.issue_id), '') AS issue_id
                                FROM events
                                {issue_state_join}
                                WHERE events.team_id IN %(team_ids)s
                                    AND events.event = '$exception'
                                    AND {in_days}
                                    AND events.`$session_id` != ''
                                    AND {lib} = 'web'
                            )
                        )
                        WHERE kind != 'pageleave'
                    )
                    GROUP BY team_id, session_id, window_id, pageview_ts
                    HAVING pageview_rows = 1
                ) AS pageviews
                LEFT JOIN (
                    SELECT team_id, person_id, groupArray({max_person_sessions})((session_id, first_ts, last_ts)) AS sessions
                    FROM (
                        SELECT
                            events.team_id AS team_id,
                            events.person_id AS person_id,
                            events.`$session_id` AS session_id,
                            min(events.timestamp) AS first_ts,
                            max(events.timestamp) AS last_ts
                        FROM events
                        WHERE events.team_id IN %(team_ids)s
                            AND events.event = '$pageview'
                            AND {in_return_days}
                            AND events.`$session_id` != ''
                        GROUP BY team_id, person_id, session_id
                    )
                    GROUP BY team_id, person_id
                ) AS returns ON returns.team_id = pageviews.team_id AND returns.person_id = pageviews.pageview_person_id
                WHERE pageviews.duration IS NULL OR pageviews.duration >= %(min_page_seconds)s
            )
            GROUP BY team_id, day_index, label, audience_key
        )
    )
    GROUP BY team_id, day_index, label
    HAVING matched_timed >= %(min_pageviews)s OR matched_all >= %(min_pageviews)s OR startsWith(label, '__')
"""


def _in_days(extra_hours: int) -> str:
    days = " OR ".join(
        f"(events.timestamp >= toDateTime64(%(day{day}_start)s, 6, 'UTC') "
        f"AND events.timestamp < toDateTime64(%(day{day}_end)s, 6, 'UTC') + toIntervalHour({extra_hours}))"
        for day in range(len(DAYS_AGO))
    )
    return f"({days})"


def _fake_labels() -> str:
    return "arrayConcat({})".format(
        ", ".join(
            f"if(modulo(cityHash64(session_id, window_id, pageview_ts, {percent}), 100) < {percent}, "
            f"['{FAKE_PREFIX}{percent}'], [])"
            for percent in FAKE_PERCENTS
        )
    )


def _query() -> str:
    return QUERY.format(
        control=CONTROL,
        fake_labels=_fake_labels(),
        window_id=property_expr("$window_id"),
        path=page_path_expr(),
        browser=property_expr("$browser"),
        device_type=property_expr("$device_type"),
        ua_class=UA_CLASS.format(ua=property_expr("$raw_user_agent")),
        issue_state_join=issue_state_join("LEFT"),
        lib=property_expr("$lib"),
        in_days=_in_days(0),
        in_return_days=_in_days(RETURN_HOURS),
        max_person_sessions=MAX_PERSON_SESSIONS,
    )


@frozen
class Days:
    """The two days the page load lenses compare, the most recent first."""

    starts: tuple[datetime, ...]

    @classmethod
    def before(cls, now: datetime) -> "Days":
        # Whole hours, so both page load lenses in one sweep read the same days and can share the result.
        hour = now.replace(minute=0, second=0, microsecond=0)
        return cls(starts=tuple(hour - timedelta(days=days_ago + 1) for days_ago in DAYS_AGO))

    def end(self, day: int) -> datetime:
        return self.starts[day] + timedelta(days=1)


@frozen
class Measure:
    """One measure of one label on one day: how many pageviews it applies to, how many it held for, and how many it
    would hold for at the comparison group's rate."""

    pageviews: int
    observed: int
    expected: float


@frozen
class PageLoadRow:
    team_id: int
    day: int
    label: str
    quick: Measure
    returned: Measure
    lost: Measure


@frozen
class Finding:
    issue_id: str
    measure: Measure
    expected_rate: float


def fetch_page_load(team_ids: list[int], days: Days) -> list[PageLoadRow]:
    """The page load rows of every team. Within one sweep batch, each team's rows are queried once for both lenses."""
    by_team = per_team_results(
        ("page_load", days.starts), team_ids, lambda missing: _query_page_load(missing, days), list
    )
    return [row for team_id in team_ids for row in by_team[team_id]]


def _query_page_load(team_ids: list[int], days: Days) -> dict[int, list[PageLoadRow]]:
    def time(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

    rows = sync_execute(
        _query(),
        {
            "team_ids": team_ids,
            **{f"day{day}_start": time(start) for day, start in enumerate(days.starts)},
            **{f"day{day}_end": time(days.end(day)) for day in range(len(days.starts))},
            "early_error_ms": EARLY_ERROR_MS,
            "min_page_seconds": MIN_PAGE_SECONDS,
            "quick_leave_before_seconds": MIN_PAGE_SECONDS + QUICK_LEAVE_SECONDS,
            "return_hours": RETURN_HOURS,
            "min_control_pageviews": MIN_CONTROL_PAGEVIEWS,
            "min_pageviews": MIN_PAGEVIEWS,
            "prior": COMPARISON_PRIOR,
        },
        workload=Workload.OFFLINE,
    )
    by_team: dict[int, list[PageLoadRow]] = defaultdict(list)
    parsed = [
        PageLoadRow(
            team_id=team_id,
            day=day,
            label=label,
            quick=Measure(pageviews=timed, observed=quick, expected=expected_quick),
            returned=Measure(pageviews=quick_leaves, observed=returned, expected=expected_returned),
            lost=Measure(pageviews=all_pageviews, observed=lost, expected=expected_lost),
        )
        for (
            team_id,
            day,
            label,
            timed,
            quick,
            expected_quick,
            quick_leaves,
            returned,
            expected_returned,
            all_pageviews,
            lost,
            expected_lost,
        ) in rows
    ]
    for row in parsed:
        by_team[row.team_id].append(row)
    return by_team


def evaluable_teams(rows: list[PageLoadRow], measure: Callable[[PageLoadRow], Measure]) -> set[int]:
    """Teams with comparison pageviews for the measure on the most recent day."""
    return {row.team_id for row in rows if row.label == CONTROL and row.day == 0 and measure(row).pageviews > 0}


def find_day_findings(
    rows: list[PageLoadRow], measure: Callable[[PageLoadRow], Measure]
) -> dict[tuple[int, int], dict[str, Finding]]:
    """Per team and day, the issues whose measure is far above the comparison group's rate."""
    fake_ratio: dict[tuple[int, int], float] = {}
    for row in rows:
        counts = measure(row)
        if row.label.startswith(FAKE_PREFIX) and counts.pageviews >= MIN_FAKE_PAGEVIEWS and counts.expected > 0:
            key = (row.team_id, row.day)
            fake_ratio[key] = max(fake_ratio.get(key, 1.0), counts.observed / counts.expected)

    findings: dict[tuple[int, int], dict[str, Finding]] = defaultdict(dict)
    for row in rows:
        counts = measure(row)
        if row.label.startswith("__") or counts.pageviews < MIN_PAGEVIEWS or not 0 < counts.expected < counts.pageviews:
            continue
        # A fake that shows an effect means the comparison is biased, so raise the bar by the same amount.
        expected = min(
            counts.expected * fake_ratio.get((row.team_id, row.day), 1.0), MAX_EXPECTED_SHARE * counts.pageviews
        )
        share = expected / counts.pageviews
        z = (counts.observed - expected) / math.sqrt(counts.pageviews * share * (1 - share))
        if z >= MIN_Z and counts.observed >= MIN_LIFT * expected:
            findings[(row.team_id, row.day)][row.label] = Finding(
                issue_id=row.label, measure=counts, expected_rate=round(share, 4)
            )
    return findings


def find_repeated_findings(
    rows: list[PageLoadRow], measure: Callable[[PageLoadRow], Measure], excluded: dict[int, set[str]]
) -> dict[int, list[Finding]]:
    """Per team, the most recent day's findings that also held a week earlier, minus the excluded issues."""
    findings = find_day_findings(rows, measure)
    result: dict[int, list[Finding]] = {}
    for (team_id, day), by_issue in findings.items():
        if day != 0:
            continue
        earlier = findings.get((team_id, 1), {})
        repeated = [
            finding
            for issue_id, finding in by_issue.items()
            if issue_id in earlier and issue_id not in excluded.get(team_id, set())
        ]
        if repeated:
            result[team_id] = sorted(
                repeated,
                key=lambda f: (-(f.measure.observed - f.expected_rate * f.measure.pageviews), f.issue_id),
            )
    return result


def returned_rates(rows: list[PageLoadRow]) -> dict[tuple[int, str], tuple[float, float]]:
    """Per team and issue on the most recent day: the share of quick leavers who came back within a day, and the share
    expected from quick leavers of the same pages without an error."""
    return {
        (row.team_id, row.label): (
            round(row.returned.observed / row.returned.pageviews, 4),
            round(row.returned.expected / row.returned.pageviews, 4),
        )
        for row in rows
        if row.day == 0 and row.returned.pageviews > 0
    }


def excluded_issues(team_ids: list[int], days: Days, rows: list[PageLoadRow]) -> dict[int, set[str]]:
    """Issues the page load lenses leave out: those that fire as people leave the page on the most recent day, since
    leaving causes them, and those that are likely noise."""
    unload = unload_issue_ids(team_ids, days.starts[0], days.end(0))
    candidates: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        if not row.label.startswith("__"):
            candidates[row.team_id].add(row.label)
    noise = noise_issue_ids(team_ids, candidates, days.starts[-1])
    return {team_id: unload.get(team_id, set()) | noise.get(team_id, set()) for team_id in team_ids}
