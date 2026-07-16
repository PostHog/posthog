from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# "token": Sumo Logic management APIs paginated with `limit` + `token` params; the response body
#     carries the record list under `data_key` plus a `next` continuation token.
# "offset": `limit` + `offset` params; a short page signals the end.
# "search_job": the async Search Job API (submit / poll / fetch) — bespoke path in sumo_logic.py.
PaginationStyle = Literal["token", "offset", "search_job"]

# First sync of the logs table reaches back this far. Log volume through the Search Job API is
# expensive (one async job per time window), so this is deliberately shorter than typical retention.
DEFAULT_LOGS_LOOKBACK_DAYS = 7


@dataclass
class SumoLogicEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. ``None`` means the body itself is the list.
    data_key: Optional[str] = None
    pagination: PaginationStyle = "token"
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Each record is nested under this key (e.g. monitors search returns {"item": {...}, "path": ...});
    # the record is lifted to the root and the remaining sibling keys are kept alongside it.
    nest_key: Optional[str] = None
    # Extra query params sent on every request (e.g. the monitors search query).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fan out over every collector, fetching this endpoint per collector id. When True, ``path`` is a
    # template with a ``{collector_id}`` placeholder.
    fan_out_over_collectors: bool = False
    # Stable, immutable datetime field used for partitioning (never a last-modified field).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Top-level keys stripped from every record before it's yielded. Used to drop credential-bearing
    # fields (e.g. webhook URLs and auth headers) that a warehouse reader must never see.
    redact_fields: frozenset[str] = frozenset()


# Endpoint catalog. The headline stream is `logs` via the async Search Job API (the only Sumo Logic
# API that exports log data, and the only one with a genuine server-side time filter — hence the only
# incremental table). The management APIs are plain paginated GETs with no server-side timestamp
# filter, so they ship as full refresh.
#
# Endpoint paths and pagination follow the official API docs (https://api.sumologic.com/docs/).
# Sumo Logic returns 401 before routing, so unauthenticated probes can't confirm paths — the catalog
# is doc-verified only.
SUMO_LOGIC_ENDPOINTS: dict[str, SumoLogicEndpointConfig] = {
    "logs": SumoLogicEndpointConfig(
        name="logs",
        path="/v1/search/jobs",
        pagination="search_job",
        # Search Job message pages max out at 10,000 messages per fetch.
        page_size=10_000,
        # `_messageid` is documented as a unique message identifier; `_messagetime` is included
        # defensively so the key stays unique even if message ids ever repeat across sources.
        primary_keys=["_messageid", "_messagetime"],
        partition_key="message_time",
        incremental_fields=[
            {
                "label": "message_time",
                "type": IncrementalFieldType.DateTime,
                "field": "message_time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "users": SumoLogicEndpointConfig(name="users", path="/v1/users", data_key="data"),
    "roles": SumoLogicEndpointConfig(name="roles", path="/v1/roles", data_key="data"),
    "collectors": SumoLogicEndpointConfig(
        name="collectors",
        path="/v1/collectors",
        data_key="collectors",
        pagination="offset",
    ),
    "collector_sources": SumoLogicEndpointConfig(
        name="collector_sources",
        path="/v1/collectors/{collector_id}/sources",
        data_key="sources",
        pagination="offset",  # applies to the parent collectors listing; the sources call is unpaginated
        # Source ids are only unique within their collector, so the parent id is part of the key.
        primary_keys=["collector_id", "id"],
        fan_out_over_collectors=True,
        # HTTP-source records carry a generated `url` that is itself a bearer credential for log
        # ingestion — anyone with it can inject arbitrary logs into the account. Drop it so a
        # warehouse reader sees the source metadata (id, name, type) without the ingestion secret.
        redact_fields=frozenset({"url"}),
    ),
    "dashboards": SumoLogicEndpointConfig(name="dashboards", path="/v2/dashboards", data_key="dashboards"),
    "monitors": SumoLogicEndpointConfig(
        name="monitors",
        path="/v1/monitors/search",
        pagination="offset",
        nest_key="item",
        extra_params={"query": "type:monitor"},
    ),
    "partitions": SumoLogicEndpointConfig(name="partitions", path="/v1/partitions", data_key="data"),
    "ingest_budgets": SumoLogicEndpointConfig(name="ingest_budgets", path="/v1/ingestBudgets", data_key="data"),
    "connections": SumoLogicEndpointConfig(
        name="connections",
        path="/v1/connections",
        data_key="data",
        # A connection definition embeds the outbound webhook secret: the destination URL carries
        # the auth token for Slack/PagerDuty-style webhooks, and the header fields can carry an
        # Authorization credential. Drop them so a warehouse reader sees that a connection exists
        # (name, type, description) without the credentials needed to forge notifications through it.
        redact_fields=frozenset({"url", "headers", "customHeaders", "defaultPayload"}),
    ),
    "field_extraction_rules": SumoLogicEndpointConfig(
        name="field_extraction_rules", path="/v1/extractionRules", data_key="data"
    ),
    "scheduled_views": SumoLogicEndpointConfig(name="scheduled_views", path="/v1/scheduledViews", data_key="data"),
    "health_events": SumoLogicEndpointConfig(
        name="health_events",
        path="/v1/healthEvents",
        data_key="data",
        primary_keys=["eventId"],
    ),
}

ENDPOINTS = tuple(SUMO_LOGIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SUMO_LOGIC_ENDPOINTS.items()
}
