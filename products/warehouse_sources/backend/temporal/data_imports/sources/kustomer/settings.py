from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class KustomerEndpointConfig:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    params: dict[str, str] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None


# Kustomer's GET list endpoints have no updated-since filter (incremental needs
# the POST search API with updatedAt windows — a possible follow-up), so every
# stream is an honest full refresh. JSON:API rows nest fields under
# `attributes`, so no top-level timestamp is available for partitioning.
# These resources are served under `/v1/` regardless of the vendor version
# pin — the "v2" API-reference toggle still documents them at `/v1/`.
KUSTOMER_ENDPOINTS: dict[str, KustomerEndpointConfig] = {
    "customers": KustomerEndpointConfig(path="/v1/customers"),
    "conversations": KustomerEndpointConfig(path="/v1/conversations"),
    "users": KustomerEndpointConfig(path="/v1/users"),
    "teams": KustomerEndpointConfig(path="/v1/teams"),
    "tags": KustomerEndpointConfig(path="/v1/tags"),
    "brands": KustomerEndpointConfig(path="/v1/brands"),
    "companies": KustomerEndpointConfig(path="/v1/companies"),
    # `resource` is required; conversation sub-statuses resolve the sub-status id on conversation rows.
    "sub_statuses": KustomerEndpointConfig(path="/v1/sub-statuses", params={"resource": "conversation"}),
    # Satisfaction (CSAT) form definitions. Responses are only readable one id at a time.
    "satisfaction_forms": KustomerEndpointConfig(path="/v1/satisfaction"),
    # These lists paginate by page number, so an ascending sort keeps rows created
    # during a sync from shifting later pages.
    "messages": KustomerEndpointConfig(path="/v1/messages", params={"sort": "asc"}),
    "notes": KustomerEndpointConfig(path="/v1/notes", params={"sort": "asc"}),
    "queues": KustomerEndpointConfig(path="/v1/routing/queues"),
    "work_items": KustomerEndpointConfig(path="/v1/routing/work-items", params={"sort": "asc"}),
    # `user=true` would return only the sessions of the user who owns the API key.
    "work_sessions": KustomerEndpointConfig(
        path="/v1/routing/work-sessions", params={"sort": "asc", "user": "false", "active": "false"}
    ),
    # Routing status definitions (available, offline, custom away statuses), not a history of agent states.
    "routing_statuses": KustomerEndpointConfig(path="/v1/routing/statuses", params={"pageSize": "100"}),
    "audit_logs": KustomerEndpointConfig(path="/v1/audit-logs"),
    # Custom object definitions. Without a `status` filter the API returns enabled klasses only.
    "klasses": KustomerEndpointConfig(path="/v1/klasses", params={"pageSize": "100"}),
    # Custom objects are listed one klass at a time. Object ids are only documented as unique
    # within their klass, so the klass id is part of the key.
    "kobjects": KustomerEndpointConfig(
        path="/v1/klasses/{name}",
        primary_keys=("klass_id", "id"),
        params={"pageSize": "100", "sort": "asc"},
        fanout=DependentEndpointConfig(
            parent_name="klasses",
            resolve_param="name",
            resolve_field="attributes.name",
            include_from_parent=["id"],
            parent_field_renames={"id": "klass_id"},
        ),
    ),
}

ENDPOINTS = tuple(KUSTOMER_ENDPOINTS.keys())

# Kustomer's GET list endpoints expose no updated-since filter, so no endpoint
# has an incremental field — every stream is a full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
