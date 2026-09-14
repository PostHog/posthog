from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# The agent endpoints wrap their rows in `data` and hand back the next page token in
# `nextCursor`, which is fed back as `cursor`.
CURSOR_PATH = "nextCursor"
CURSOR_PARAM = "cursor"

# Largest `limit` those endpoints accept, so a sync makes as few round trips as it can.
MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class BrowserbaseEndpointConfig:
    name: str
    path: str
    # Field to partition Delta files by. Must be a stable creation-time timestamp so a row never
    # moves between partitions (Browserbase mutates `updatedAt`/`endedAt`, so those are unsafe).
    partition_key: str | None = None
    # Incremental cursor candidates. Left empty for every Browserbase endpoint. The session,
    # project and log endpoints expose no server-side timestamp filter at all. The agent
    # endpoints do accept `startAt`/`endAt`, but both filter on *creation* time while the rows
    # keep changing after creation — a run walks PENDING to RUNNING to COMPLETED, and an agent's
    # prompt can be edited — so a creation-time cursor would freeze every row at the state it
    # had when it was first seen. Full refresh is the honest strategy.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # jsonpath to the row list, for the endpoints that wrap rows in an envelope. None where the
    # whole response body is the rows.
    data_selector: str | None = None
    # True for the endpoints that take `cursor`/`limit`. The rest return the whole collection in
    # one response and accept no paging params.
    paginated: bool = False
    # `/projects/{id}/usage` answers with a single object rather than a row list, so the
    # fail-loud list-shape check does not apply to it.
    returns_object: bool = False
    # Read only by the fan-out helper's protocol. Browserbase's fan-out parents and children take
    # no page-size param, so no request ever sends it.
    page_size: int = MAX_PAGE_SIZE
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


BROWSERBASE_ENDPOINTS: dict[str, BrowserbaseEndpointConfig] = {
    "sessions": BrowserbaseEndpointConfig(
        name="sessions",
        path="/sessions",
        partition_key="createdAt",
        primary_keys=["id"],
    ),
    "projects": BrowserbaseEndpointConfig(
        name="projects",
        path="/projects",
        partition_key="createdAt",
        primary_keys=["id"],
    ),
    "agents": BrowserbaseEndpointConfig(
        name="agents",
        path="/agents",
        partition_key="createdAt",
        primary_keys=["agentId"],
        data_selector="data",
        paginated=True,
    ),
    "agent_runs": BrowserbaseEndpointConfig(
        name="agent_runs",
        path="/agents/runs",
        partition_key="createdAt",
        primary_keys=["runId"],
        data_selector="data",
        paginated=True,
    ),
    "project_usage": BrowserbaseEndpointConfig(
        name="project_usage",
        path="/projects/{project_id}/usage",
        # The usage body is a bare {browserMinutes, proxyBytes} object with no id and no
        # timestamp: the project it was read for is the whole key, and there is nothing stable
        # to partition on.
        primary_keys=["projectId"],
        returns_object=True,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "projectId"},
        ),
    ),
    "session_logs": BrowserbaseEndpointConfig(
        name="session_logs",
        path="/sessions/{session_id}/logs",
        # Log lines carry no id of their own, so a CDP message is identified by the session and
        # page it ran on, its method, and when it fired. `timestamp` is epoch milliseconds rather
        # than a datetime, so it cannot serve as a partition key.
        primary_keys=["sessionId", "pageId", "method", "timestamp"],
        # One request per session, over a session list the API returns unpaginated, with the raw
        # CDP request and response bodies in every row. Too heavy to turn on for everyone.
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="sessions",
            resolve_param="session_id",
            resolve_field="id",
            # Log rows already carry `sessionId`, but copying the parent id down under the same
            # name keeps the primary key intact even for a row that omits it.
            include_from_parent=["id"],
            parent_field_renames={"id": "sessionId"},
        ),
    ),
}

ENDPOINTS = tuple(BROWSERBASE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BROWSERBASE_ENDPOINTS.items()
}
