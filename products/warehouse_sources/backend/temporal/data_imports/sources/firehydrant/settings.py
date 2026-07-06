from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FireHydrantEndpointConfig:
    path: str
    # Field to partition by. Must be a STABLE creation timestamp (never updated_at), and only set
    # when the endpoint's entity actually returns it — several FireHydrant resources don't.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# Endpoint catalog. Paths are the FireHydrant v1 REST collection endpoints (verified against the
# official OpenAPI spec). Every endpoint is full refresh only: FireHydrant exposes no uniform
# server-side `updated_after` cursor across resources, so we don't advertise incremental fields here
# (matching Airbyte's connector, which is also full-refresh only). `/v1/incidents` does accept
# `created_at_or_after` / `updated_after` filters, but we couldn't curl-verify they actually filter
# (no live credentials), so incremental sync for incidents is left as a future enhancement.
FIREHYDRANT_ENDPOINTS: dict[str, FireHydrantEndpointConfig] = {
    "incidents": FireHydrantEndpointConfig(path="/v1/incidents", partition_key="created_at"),
    "alerts": FireHydrantEndpointConfig(path="/v1/alerts"),
    "changes": FireHydrantEndpointConfig(path="/v1/changes", partition_key="created_at"),
    "change_events": FireHydrantEndpointConfig(path="/v1/changes/events", partition_key="created_at"),
    "environments": FireHydrantEndpointConfig(path="/v1/environments", partition_key="created_at"),
    "functionalities": FireHydrantEndpointConfig(path="/v1/functionalities", partition_key="created_at"),
    "services": FireHydrantEndpointConfig(path="/v1/services", partition_key="created_at"),
    "teams": FireHydrantEndpointConfig(path="/v1/teams", partition_key="created_at"),
    "users": FireHydrantEndpointConfig(path="/v1/users", partition_key="created_at"),
    "incident_roles": FireHydrantEndpointConfig(path="/v1/incident_roles", partition_key="created_at"),
    "incident_types": FireHydrantEndpointConfig(path="/v1/incident_types", partition_key="created_at"),
    # TagEntity only carries `name`; it has no id or created_at, so the name is the natural key.
    "incident_tags": FireHydrantEndpointConfig(path="/v1/incident_tags", primary_keys=["name"]),
    # PriorityEntity / SeverityEntity are keyed by their human-readable slug, not a UUID.
    "priorities": FireHydrantEndpointConfig(path="/v1/priorities", primary_keys=["slug"], partition_key="created_at"),
    "severities": FireHydrantEndpointConfig(path="/v1/severities", primary_keys=["slug"], partition_key="created_at"),
    "custom_field_definitions": FireHydrantEndpointConfig(
        path="/v1/custom_fields/definitions", primary_keys=["field_id"]
    ),
    "integrations": FireHydrantEndpointConfig(path="/v1/integrations", partition_key="created_at"),
    "runbooks": FireHydrantEndpointConfig(path="/v1/runbooks", partition_key="created_at"),
    "runbook_executions": FireHydrantEndpointConfig(path="/v1/runbooks/executions", partition_key="created_at"),
    "webhooks": FireHydrantEndpointConfig(path="/v1/webhooks", partition_key="created_at"),
    # Undocumented response shape in the spec; handled defensively in transport. No created_at to partition on.
    "signals_on_call": FireHydrantEndpointConfig(path="/v1/signals_on_call"),
    "post_mortem_reports": FireHydrantEndpointConfig(path="/v1/post_mortems/reports", partition_key="created_at"),
    "scheduled_maintenances": FireHydrantEndpointConfig(path="/v1/scheduled_maintenances", partition_key="created_at"),
    "task_lists": FireHydrantEndpointConfig(path="/v1/task_lists", partition_key="created_at"),
    "checklist_templates": FireHydrantEndpointConfig(path="/v1/checklist_templates", partition_key="created_at"),
}

ENDPOINTS = tuple(FIREHYDRANT_ENDPOINTS.keys())

# Every endpoint is full refresh only — no advertised incremental options. Kept as an explicit map so
# the source class and tests can reason about it the same way as other sources.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FIREHYDRANT_ENDPOINTS.items()
}
