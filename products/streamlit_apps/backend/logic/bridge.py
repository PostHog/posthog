from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

if TYPE_CHECKING:
    from posthog.models.user import User

logger = logging.getLogger(__name__)

# Tighter than HogQL defaults so a misbehaving sandbox can't exhaust a query node.
BRIDGE_MAX_EXECUTION_TIME_SECONDS = 30
BRIDGE_MAX_MEMORY_USAGE_BYTES = 256 * 1024 * 1024  # 256 MB
BRIDGE_MAX_BYTES_TO_READ = 5 * 1024 * 1024 * 1024  # 5 GB


def execute_bridge_query(query: str, team_id: int, user: User | None, client_query_id: str | None = None) -> dict:
    from posthog.clickhouse.query_tagging import tag_queries

    team = Team.objects.get(id=team_id)
    tag_queries(
        kind="streamlit_bridge",
        team_id=team_id,
        client_query_id=client_query_id or "",
    )
    # The bridge token's minting user carries the access-control context: warehouse
    # table/view ACLs fail closed without a user, so a userless run would deny every
    # warehouse table — and running as anyone broader would bypass table-level RBAC.
    response = execute_hogql_query(
        query=query,
        team=team,
        user=user,
        limit_context=LimitContext.POSTHOG_AI,
        settings=HogQLGlobalSettings(
            max_execution_time=BRIDGE_MAX_EXECUTION_TIME_SECONDS,
            max_memory_usage=BRIDGE_MAX_MEMORY_USAGE_BYTES,
            max_bytes_to_read=BRIDGE_MAX_BYTES_TO_READ,
        ),
    )

    # Deliberate allow-list off the typed response: HogQLQueryResponse also carries
    # internal fields (hogql, the ClickHouse query, explain, timings) that sandbox
    # user code must never see. Read the three presentation fields by name rather
    # than dumping the whole model and re-picking string keys.
    return {
        "columns": response.columns or [],
        "results": response.results or [],
        "types": response.types or [],
    }
