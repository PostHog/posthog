from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# FireHydrant caps per_page at 200. 100 keeps each response comfortably small while halving the
# request count versus the default page size.
PAGE_SIZE = 100


@frozen
class FireHydrantEndpointConfig:
    path: str
    # Field to partition by. Must be a STABLE creation timestamp (never updated_at), and only set
    # when the endpoint's entity actually returns it — several FireHydrant resources don't.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Set when the endpoint is scoped to a parent resource and has to be walked once per parent row.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    # Read by the shared fan-out builder; every FireHydrant endpoint is full refresh, so it stays None.
    default_incremental_field: Optional[str] = None
    # JSON path the rows live under. Nearly every endpoint uses the paginated `data` envelope;
    # /v1/services/{service_id}/dependencies answers with a named array instead.
    data_selector: str = "data"


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
    # ScheduleEntity carries only id/name/integration/discarded, so there is nothing to partition on.
    "schedules": FireHydrantEndpointConfig(path="/v1/schedules"),
    "incident_milestones": FireHydrantEndpointConfig(
        path="/v1/incidents/{incident_id}/milestones",
        partition_key="created_at",
        # Milestone ids are only documented per incident, and this table aggregates every incident's
        # milestones, so the parent incident is part of the key to keep it unique table-wide.
        primary_keys=["incident_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
        ),
    ),
    "incident_tasks": FireHydrantEndpointConfig(
        path="/v1/incidents/{incident_id}/tasks",
        partition_key="created_at",
        primary_keys=["incident_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
        ),
    ),
    # The spec documents the request but leaves the response body empty, as it does for 100+ other
    # FireHydrant endpoints (signals_on_call included). Transport reads the standard `data` envelope
    # and fails loud if this endpoint turns out to answer differently.
    "team_escalation_policies": FireHydrantEndpointConfig(
        path="/v1/teams/{team_id}/escalation_policies",
        primary_keys=["team_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="teams",
            resolve_param="team_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "team_id"},
        ),
    ),
    # IncidentEventEntity carries no created_at; occurred_at is the (immutable) time the timeline
    # entry happened, so it is the stable field to partition on.
    "incident_events": FireHydrantEndpointConfig(
        path="/v1/incidents/{incident_id}/events",
        partition_key="occurred_at",
        primary_keys=["incident_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
        ),
    ),
    "incident_role_assignments": FireHydrantEndpointConfig(
        path="/v1/incidents/{incident_id}/role_assignments",
        partition_key="created_at",
        primary_keys=["incident_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
        ),
    ),
    # Dependency edges are shared between the two services they join, so the same edge id comes back
    # under both endpoints; the parent service is what makes each row unique.
    "service_dependencies": FireHydrantEndpointConfig(
        path="/v1/services/{service_id}/dependencies",
        partition_key="created_at",
        primary_keys=["service_id", "id"],
        data_selector="service_dependencies",
        fanout=DependentEndpointConfig(
            parent_name="services",
            resolve_param="service_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "service_id"},
            # `flatten` collapses the parent/child arrays into `service_dependencies`; each row keeps
            # a `type` saying which direction the edge runs. Sent as a lowercase string because the
            # API rejects Python's `True` repr.
            child_params={"flatten": "true"},
        ),
    ),
}

ENDPOINTS = tuple(FIREHYDRANT_ENDPOINTS.keys())

# Every endpoint is full refresh only — no advertised incremental options. Kept as an explicit map so
# the source class and tests can reason about it the same way as other sources.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FIREHYDRANT_ENDPOINTS.items()
}
