from collections.abc import Sequence
from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models import Team

PERSON_LIBS = ("web", "posthog-ios", "posthog-android", "posthog-react-native", "posthog-flutter")
WEEKS = 4
SERIES_DAYS = 14
ROW_LIMIT = 60
MAX_EXECUTION_SECONDS = 60


def _window(week: int) -> str:
    return (
        f"(timestamp > {{anchor}} - INTERVAL {7 * week + 1} DAY AND timestamp <= {{anchor}} - INTERVAL {7 * week} DAY)"
    )


WINDOWS = [_window(week) for week in range(WEEKS + 1)]
IN_WINDOWS = " OR ".join(WINDOWS)


def _per_window(aggregate: str) -> str:
    return ", ".join(f"{aggregate.format(cond=cond)} AS w{index}" for index, cond in enumerate(WINDOWS))


PEOPLE = _per_window("uniqIf(person_id, {cond})")
COUNTS = _per_window("countIf({cond})")
FROM_PEOPLE = "properties.$lib IN {person_libs}"

ACTIONS = f"""
SELECT event, {PEOPLE} FROM events
WHERE ({IN_WINDOWS}) AND {FROM_PEOPLE} AND NOT startsWith(event, '$')
GROUP BY event HAVING w0 >= 100 OR w1 >= 100 ORDER BY w0 DESC LIMIT {ROW_LIMIT}
"""

ERRORS = f"""
SELECT toString(issue_id), any(properties.$exception_types[1]), any(substring(properties.$exception_values[1], 1, 120)),
topK(1)(properties.$pathname)[1], any(properties.$host), {PEOPLE}
FROM events
WHERE event = '$exception' AND ({IN_WINDOWS}) AND {FROM_PEOPLE}
GROUP BY issue_id HAVING w0 >= 50 ORDER BY w0 DESC LIMIT {ROW_LIMIT}
"""

SURVEYS = f"""
SELECT toString(properties.$survey_id), any(properties.$survey_name), substring(toString(properties.$survey_response), 1, 80), {COUNTS}
FROM events
WHERE event = 'survey sent' AND ({IN_WINDOWS}) AND length(toString(properties.$survey_response)) BETWEEN 1 AND 80
GROUP BY 1, 3 HAVING w0 >= 10 ORDER BY w0 DESC LIMIT {ROW_LIMIT}
"""

TRAFFIC = f"""
SELECT coalesce(properties.$host, ''), {PEOPLE} FROM events
WHERE event = '$pageview' AND ({IN_WINDOWS}) AND {FROM_PEOPLE}
GROUP BY 1 HAVING w0 >= 200 ORDER BY w0 DESC LIMIT 15
"""

KEY_EVENTS = f"""
SELECT event, {COUNTS} FROM events
WHERE ({IN_WINDOWS}) AND NOT startsWith(event, '$')
GROUP BY event HAVING w0 >= 100 OR w1 >= 100 ORDER BY w0 DESC LIMIT {ROW_LIMIT}
"""

DAY = "intDiv(dateDiff('second', timestamp, {anchor}), 86400)"
IN_SERIES = f"timestamp > {{anchor}} - INTERVAL {SERIES_DAYS} DAY AND timestamp <= {{anchor}}"

SERIES = {
    "error": f"""SELECT toString(issue_id), {DAY}, uniq(person_id) FROM events
WHERE event = '$exception' AND {IN_SERIES} AND {FROM_PEOPLE} AND toString(issue_id) IN {{keys}} GROUP BY 1, 2 LIMIT 1000""",
    "key metric": f"""SELECT event, {DAY}, count() FROM events
WHERE {IN_SERIES} AND event IN {{keys}} GROUP BY 1, 2 LIMIT 1000""",
    "user action": f"""SELECT event, {DAY}, uniq(person_id) FROM events
WHERE {IN_SERIES} AND {FROM_PEOPLE} AND event IN {{keys}} GROUP BY 1, 2 LIMIT 1000""",
    "survey answer": f"""SELECT concat(toString(properties.$survey_id), '|', substring(toString(properties.$survey_response), 1, 80)), {DAY}, count()
FROM events WHERE event = 'survey sent' AND {IN_SERIES}
AND concat(toString(properties.$survey_id), '|', substring(toString(properties.$survey_response), 1, 80)) IN {{keys}} GROUP BY 1, 2 LIMIT 1000""",
    "visitors": f"""SELECT coalesce(properties.$host, ''), {DAY}, uniq(person_id) FROM events
WHERE event = '$pageview' AND {IN_SERIES} AND {FROM_PEOPLE} AND coalesce(properties.$host, '') IN {{keys}} GROUP BY 1, 2 LIMIT 1000""",
}


def _strings(values: Sequence[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in values])


def run(team: Team, statement: str, anchor: datetime, name: str, **values: Sequence[str]) -> list[tuple[Any, ...]]:
    placeholders: dict[str, ast.Expr] = {"anchor": ast.Constant(value=anchor), "person_libs": _strings(PERSON_LIBS)}
    placeholders.update({key: _strings(value) for key, value in values.items()})
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(
            query=parse_select(statement, placeholders=placeholders),
            team=team,
            query_type=f"today_news_{name}",
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_SECONDS),
        )
    return list(response.results or [])
