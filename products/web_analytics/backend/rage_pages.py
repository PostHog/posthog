from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team, User

QUERY_TIMEOUT_SECONDS = 10
MIN_CLICKS_PER_PERSON = 10
MIN_PEOPLE = 3
ERROR_WINDOW_SECONDS = 30
RAGE_PATH = "replaceRegexpAll(coalesce(properties.$pathname, ''), '/[0-9a-f-]{8,}|/[0-9]+', '/…')"
TOP_RAGE_PAGE = f"""
SELECT path, count() AS people, sum(clicks) AS clicks FROM (
    SELECT person_id, {RAGE_PATH} AS path, count() AS clicks
    FROM events WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$rageclick'
    GROUP BY person_id, path HAVING clicks >= {MIN_CLICKS_PER_PERSON}
)
GROUP BY path HAVING people >= {MIN_PEOPLE} ORDER BY people DESC, clicks DESC
LIMIT 1
"""
TOP_RAGE_ELEMENT = f"""
SELECT arrayElement(elements_chain_texts, 1) AS text, count() AS clicks FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$rageclick'
  AND {RAGE_PATH} = {{path}}
  AND arrayElement(elements_chain_texts, 1) != ''
GROUP BY text ORDER BY clicks DESC
LIMIT 1
"""
QUALIFYING_PEOPLE = f"""
SELECT person_id FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$rageclick' AND {RAGE_PATH} = {{path}}
GROUP BY person_id HAVING count() >= {MIN_CLICKS_PER_PERSON}
"""
ERRORS_BEFORE_RAGE = f"""
WITH qualifying_sessions AS MATERIALIZED (
    SELECT `$session_id` AS session_id, min(timestamp) AS first_rage FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$rageclick' AND `$session_id` != ''
      AND {RAGE_PATH} = {{path}} AND person_id IN ({QUALIFYING_PEOPLE})
    GROUP BY session_id
)
SELECT r.session_id AS session_id,
       groupUniqArrayIf(
           x.issue,
           isNotNull(x.issue)
           AND x.timestamp >= r.first_rage - INTERVAL {ERROR_WINDOW_SECONDS} SECOND
           AND x.timestamp <= r.first_rage
       ) AS issues
FROM qualifying_sessions AS r
LEFT JOIN (
    SELECT `$session_id` AS session_id, timestamp, toString(issue_id) AS issue FROM events
    WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$exception'
      AND `$session_id` IN (SELECT session_id FROM qualifying_sessions)
) AS x ON x.session_id = r.session_id
GROUP BY r.session_id
LIMIT 10000
"""


@dataclass(frozen=True)
class RagePage:
    path: str
    people: int
    clicks: int


@dataclass(frozen=True)
class ErrorsBeforeRage:
    sessions: int
    issue_id: str | None
    issue_sessions: int


def _rows(query: str, team: "Team", user: "User", name: str, path: str | None = None) -> list[Any]:
    return execute_hogql_query(
        query,
        team,
        query_type=name,
        placeholders={"path": ast.Constant(value=path)} if path is not None else {},
        user=user,
        settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
    ).results


def find_top_rage_page(team: "Team", user: "User") -> RagePage | None:
    rows = _rows(TOP_RAGE_PAGE, team, user, "web_analytics_top_rage_page")
    return RagePage(path=rows[0][0], people=rows[0][1], clicks=rows[0][2]) if rows else None


def find_top_rage_element(team: "Team", user: "User", path: str) -> str | None:
    rows = _rows(TOP_RAGE_ELEMENT, team, user, "web_analytics_top_rage_element", path)
    return rows[0][0] if rows else None


def find_errors_before_rage(team: "Team", user: "User", path: str) -> ErrorsBeforeRage:
    rows = _rows(ERRORS_BEFORE_RAGE, team, user, "web_analytics_errors_before_rage", path)
    issues = Counter(issue for _, session_issues in rows for issue in session_issues)
    issue_id, issue_sessions = issues.most_common(1)[0] if issues else (None, 0)
    return ErrorsBeforeRage(sessions=len(rows), issue_id=issue_id, issue_sessions=issue_sessions)
