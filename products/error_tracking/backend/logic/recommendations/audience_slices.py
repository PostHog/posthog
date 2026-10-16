import math
from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .impact_lens import MAX_ISSUES, WINDOW_HOURS, ImpactLens, issue_state_join, property_expr, with_issue_details
from .known_patterns import noise_issue_ids

MIN_ISSUE_SESSIONS = 60
# Share of the issue's sessions that must carry a pageview id. Below it, the issue comes from a surface that
# sends no pageviews, and pageview traffic is the wrong baseline for it.
MIN_PAGEVIEW_COVERAGE = 0.5
MIN_BASELINE_SESSIONS = 100
MIN_SHARE = 0.3
MIN_LIFT = 3.0
# A value the baseline barely has still gets a finite share: at least this many sessions over the baseline total.
MIN_BASELINE_SESSIONS_FLOOR = 2
MAX_BASELINE_SHARE = 0.999
# Keeps the per-team row count bounded, largest issues first.
MAX_SLICE_ROWS = 2000
MIN_Z = 6.0
MAX_SLICES_PER_ISSUE = 3

DIMENSIONS = ("browser", "browser_version", "os", "device_type", "user_agent")

BOT_PATTERN = r"(?i)bot|crawl|spider|headless|lighthouse|phantomjs|puppeteer|playwright|pingdom|gtmetrix|ptst|slurp"
IN_APP_BROWSER_PATTERN = (
    r"FBAN|FBAV|FB_IAB|Instagram|TikTok|musical_ly|Bytedance|Snapchat|LinkedInApp|Pinterest|Line/|MicroMessenger|GSA/"
)
WEBVIEW_PATTERN = r"; wv\\)|WebView"

DIMENSION_VALUES = """[
    ('browser', {browser}),
    ('browser_version', if({browser} != '' AND {browser_version} != '', concat({browser}, ' ', splitByChar('.', {browser_version})[1]), '')),
    ('os', {os}),
    ('device_type', {device_type}),
    ('user_agent', multiIf(
        match({user_agent}, '{bot}'), 'bot',
        match({user_agent}, '{in_app}'), 'in_app_browser',
        match({user_agent}, '{webview}'), 'webview',
        ''))
]"""

ISSUE_QUERY = """
    SELECT team_id, issue_id, dim, val, sessions, issue_sessions, pageview_sessions
    FROM (
        SELECT
            team_id,
            issue_id,
            dim,
            val,
            sessions,
            max(if(dim = '__total', sessions, 0)) OVER (PARTITION BY team_id, issue_id) AS issue_sessions,
            max(if(dim = '__pageview' AND val = '1', sessions, 0)) OVER (PARTITION BY team_id, issue_id) AS pageview_sessions
        FROM (
            SELECT team_id, issue_id, tupleElement(dv, 1) AS dim, tupleElement(dv, 2) AS val, uniqExact(session_id) AS sessions
            FROM (
                SELECT
                    events.team_id AS team_id,
                    issue_state.issue_id AS issue_id,
                    events.`$session_id` AS session_id,
                    arrayJoin(arrayConcat(
                        [('__total', ''), ('__pageview', if({pageview_id} != '', '1', '0'))],
                        {dimension_values}
                    )) AS dv
                FROM events
                {issue_state_join}
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$exception'
                    AND events.timestamp >= now() - toIntervalHour(%(window_hours)s)
                    AND events.`$session_id` != ''
                    AND {lib} = 'web'
                    AND issue_state.issue_status = 'active'
            )
            GROUP BY team_id, issue_id, dim, val
        )
    )
    WHERE issue_sessions >= %(min_issue_sessions)s
        AND dim NOT IN ('__total', '__pageview')
        AND val != ''
        AND sessions >= %(min_share)s * issue_sessions
    ORDER BY team_id, issue_sessions DESC, issue_id, dim, val
    LIMIT %(max_slice_rows)s BY team_id
"""

BASELINE_QUERY = """
    SELECT team_id, tupleElement(dv, 1) AS dim, tupleElement(dv, 2) AS val, uniq(session_id) AS sessions
    FROM (
        SELECT
            events.team_id AS team_id,
            events.`$session_id` AS session_id,
            arrayJoin(arrayConcat([('__total', '')], {dimension_values})) AS dv
        FROM events
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$pageview'
            AND events.timestamp >= now() - toIntervalHour(%(window_hours)s)
            AND events.`$session_id` != ''
            AND {lib} = 'web'
    )
    WHERE dim = '__total' OR val != ''
    GROUP BY team_id, dim, val
"""


def _dimension_values() -> str:
    return DIMENSION_VALUES.format(
        browser=property_expr("$browser"),
        browser_version=property_expr("$browser_version"),
        os=property_expr("$os"),
        device_type=property_expr("$device_type"),
        user_agent=property_expr("$raw_user_agent"),
        bot=BOT_PATTERN,
        in_app=IN_APP_BROWSER_PATTERN,
        webview=WEBVIEW_PATTERN,
    )


@frozen
class SliceRow:
    """The sessions of one issue with one audience value, next to the issue's sessions in total and with a pageview."""

    team_id: int
    issue_id: str
    dimension: str
    value: str
    sessions: int
    issue_sessions: int
    pageview_sessions: int


@frozen
class BaselineRow:
    """The team's pageview sessions with one audience value, or in total for the dimension ``__total``."""

    team_id: int
    dimension: str
    value: str
    sessions: int


def evaluable_teams(baseline_rows: list[BaselineRow]) -> set[int]:
    """Teams with enough pageview traffic to compare an issue's audience with."""
    return {
        row.team_id for row in baseline_rows if row.dimension == "__total" and row.sessions >= MIN_BASELINE_SESSIONS
    }


def find_audience_slices(
    issue_rows: list[SliceRow], baseline_rows: list[BaselineRow]
) -> dict[int, list[dict[str, Any]]]:
    """Pick the audience values each issue is concentrated in, compared with the team's pageview traffic."""
    baseline_total: dict[int, int] = {}
    baseline: dict[tuple[int, str, str], int] = {}
    for base in baseline_rows:
        if base.dimension == "__total":
            baseline_total[base.team_id] = base.sessions
        else:
            baseline[(base.team_id, base.dimension, base.value)] = base.sessions

    slices_by_issue: dict[tuple[int, str], dict[str, Any]] = {}
    for row in issue_rows:
        total = baseline_total.get(row.team_id, 0)
        if row.dimension not in DIMENSIONS or not row.value.strip() or total < MIN_BASELINE_SESSIONS:
            continue
        if (
            row.issue_sessions < MIN_ISSUE_SESSIONS
            or row.pageview_sessions < MIN_PAGEVIEW_COVERAGE * row.issue_sessions
        ):
            continue
        share = row.sessions / row.issue_sessions
        baseline_sessions = max(baseline.get((row.team_id, row.dimension, row.value), 0), MIN_BASELINE_SESSIONS_FLOOR)
        baseline_share = min(baseline_sessions / total, MAX_BASELINE_SHARE)
        if share < MIN_SHARE or share < MIN_LIFT * baseline_share:
            continue
        z = (share - baseline_share) / math.sqrt(baseline_share * (1 - baseline_share) / row.issue_sessions)
        if z < MIN_Z:
            continue
        issue = slices_by_issue.setdefault(
            (row.team_id, row.issue_id), {"id": row.issue_id, "sessions": row.issue_sessions, "slices": []}
        )
        issue["slices"].append(
            {
                "dimension": row.dimension,
                "value": row.value,
                "sessions": row.sessions,
                "issue_share": round(share, 4),
                "baseline_share": round(baseline_share, 4),
                "lift": round(share / baseline_share, 1),
            }
        )

    result: dict[int, list[dict[str, Any]]] = {}
    for (team_id, _), issue in slices_by_issue.items():
        issue["slices"] = sorted(issue["slices"], key=lambda s: -s["lift"])[:MAX_SLICES_PER_ISSUE]
        result.setdefault(team_id, []).append(issue)
    for team_id, issues in result.items():
        result[team_id] = sorted(issues, key=lambda i: (-i["slices"][0]["lift"], -i["sessions"]))[:MAX_ISSUES]
    return result


class AudienceSlicesRecommendation(ImpactLens):
    type = "audience_slices"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:audience_slices",
        )
        params = {
            "team_ids": team_ids,
            "window_hours": WINDOW_HOURS,
            "min_issue_sessions": MIN_ISSUE_SESSIONS,
            "min_share": MIN_SHARE,
            "max_slice_rows": MAX_SLICE_ROWS,
        }
        dimension_values = _dimension_values()
        lib = property_expr("$lib")
        issue_rows = [
            SliceRow(
                team_id=team_id,
                issue_id=str(issue_id),
                dimension=dim,
                value=val,
                sessions=sessions,
                issue_sessions=issue_sessions,
                pageview_sessions=pageview_sessions,
            )
            for team_id, issue_id, dim, val, sessions, issue_sessions, pageview_sessions in sync_execute(
                ISSUE_QUERY.format(
                    dimension_values=dimension_values,
                    pageview_id=property_expr("$pageview_id"),
                    issue_state_join=issue_state_join(),
                    lib=lib,
                ),
                params,
                workload=Workload.OFFLINE,
            )
        ]
        baseline_rows = [
            BaselineRow(team_id=team_id, dimension=dim, value=val, sessions=sessions)
            for team_id, dim, val, sessions in sync_execute(
                BASELINE_QUERY.format(dimension_values=dimension_values, lib=lib),
                params,
                workload=Workload.OFFLINE,
            )
        ]
        evaluable = evaluable_teams(baseline_rows)
        noise = noise_issue_ids(team_ids)
        issue_rows = [row for row in issue_rows if row.issue_id not in noise.get(row.team_id, set())]
        issues = with_issue_details(team_ids, find_audience_slices(issue_rows, baseline_rows))
        return {
            team_id: {"window_hours": WINDOW_HOURS, "evaluable": team_id in evaluable, "issues": issues[team_id]}
            for team_id in team_ids
        }
