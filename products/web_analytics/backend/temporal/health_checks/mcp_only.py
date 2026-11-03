from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

MCP_ONLY_LOOKBACK_DAYS = 30

# Every MCP analytics SDK sends `$mcp_initialize` and `$mcp_tool_call`, so these two identify an MCP server project.
# A project that sends them and no `$pageview` or `$screen` has no website or app to instrument, and the web checks
# that ask for browser events or authorized URLs do not apply to it.
MCP_ONLY_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN ('$mcp_initialize', '$mcp_tool_call', '$pageview', '$screen')
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
HAVING countIf(event IN ('$pageview', '$screen')) = 0
"""


def mcp_only_team_ids(team_ids: list[int]) -> set[int]:
    rows = execute_clickhouse_health_team_query(MCP_ONLY_SQL, team_ids=team_ids, lookback_days=MCP_ONLY_LOOKBACK_DAYS)
    return {team_id for (team_id,) in rows}
