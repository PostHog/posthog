from __future__ import annotations

import logging

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

logger = logging.getLogger(__name__)

# Cap ClickHouse execution time for bridge queries so a misbehaving Streamlit
# app can't tie up a query node indefinitely. Default HogQL ceiling is 60s.
BRIDGE_MAX_EXECUTION_TIME_SECONDS = 30
# Memory and bytes-read caps are smaller than the HogQL defaults because user
# code in a sandbox shouldn't be able to drain query-node resources.
BRIDGE_MAX_MEMORY_USAGE_BYTES = 256 * 1024 * 1024  # 256 MB
BRIDGE_MAX_BYTES_TO_READ = 5 * 1024 * 1024 * 1024  # 5 GB


def execute_bridge_query(query: str, team_id: int, client_query_id: str | None = None) -> dict:
    from posthog.clickhouse.query_tagging import tag_queries

    team = Team.objects.get(id=team_id)
    tag_queries(
        kind="streamlit_bridge",
        team_id=team_id,
        client_query_id=client_query_id or "",
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        limit_context=LimitContext.POSTHOG_AI,
        settings=HogQLGlobalSettings(
            max_execution_time=BRIDGE_MAX_EXECUTION_TIME_SECONDS,
            max_memory_usage=BRIDGE_MAX_MEMORY_USAGE_BYTES,
            max_bytes_to_read=BRIDGE_MAX_BYTES_TO_READ,
        ),
    )

    if hasattr(response, "model_dump"):
        payload = response.model_dump(exclude_none=True)
    else:
        payload = response.dict(exclude_none=True)

    # Whitelist the response shape: only the columns/results/types fields are
    # exposed to the in-sandbox shim. Drop everything else (clickhouse SQL,
    # hogql AST, internal timings, modifiers) so we don't accidentally surface
    # PostHog internals to user code.
    return {
        "columns": payload.get("columns") or [],
        "results": payload.get("results") or [],
        "types": payload.get("types") or [],
    }
