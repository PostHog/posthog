from __future__ import annotations

import logging

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

logger = logging.getLogger(__name__)

# Tighter than HogQL defaults so a misbehaving sandbox can't exhaust a query node.
BRIDGE_MAX_EXECUTION_TIME_SECONDS = 30
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

    # Deliberate allow-list, not a serializer: the HogQL response also carries
    # internal fields (generated SQL, the ClickHouse query, timings, explain) that
    # sandbox user code must never see. A broader query-response serializer would
    # leak them, so we hand back only the three presentation fields.
    return {
        "columns": payload.get("columns") or [],
        "results": payload.get("results") or [],
        "types": payload.get("types") or [],
    }
