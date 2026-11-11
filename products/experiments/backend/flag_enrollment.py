from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.models.user import User

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_flag_evaluations_read_mode

QUERY_TIMEOUT_SECONDS = 10
ENROLLED_FROM_EVENTS = """
SELECT properties.$feature_flag AS flag_key, uniq(person_id) AS people
FROM events
WHERE event = '$feature_flag_called'
  AND timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY AND timestamp < toStartOfDay(now())
  AND properties.$feature_flag IN {flag_keys}
  AND toString(properties.$feature_flag_response) NOT IN ('', 'false')
GROUP BY flag_key
"""
ENROLLED_FROM_EVALUATIONS = """
SELECT flag_key, uniq(person_id) AS people
FROM posthog.flag_evaluations
WHERE timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY AND timestamp < toStartOfDay(now())
  AND flag_key IN {flag_keys}
  AND response NOT IN ('', 'false', 'null')
GROUP BY flag_key
"""


def enrolled_people_by_flag(team: Team, user: User, flag_keys: list[str]) -> dict[str, int]:
    if not flag_keys:
        return {}
    from_events = get_flag_evaluations_read_mode(team.organization_id) == FlagEvaluationsMode.EVENTS
    result = execute_hogql_query(
        ENROLLED_FROM_EVENTS if from_events else ENROLLED_FROM_EVALUATIONS,
        team,
        query_type="experiments_enrolled_people_by_flag",
        placeholders={"flag_keys": ast.Constant(value=flag_keys)},
        user=user,
        settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
    )
    return dict(result.results or [])
