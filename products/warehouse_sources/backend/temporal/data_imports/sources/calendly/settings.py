from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PAGE_SIZE = 100

# Binding values derived from a fan-out parent's `uri` (see `_with_parent_lookup_fields`), because
# no Calendly resource carries its own UUID or an escaped copy of its URI.
PARENT_UUID_FIELD = "_uuid"
PARENT_URI_PARAM_FIELD = "_uri_param"


@dataclass(frozen=True)
class CalendlyEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param used to scope the request to the user's organization. Every Calendly v2
    # list endpoint we sync requires this (an `organization` URI).
    scope_param: Optional[str] = "organization"
    # Stable field used for datetime partitioning. Never use `updated_at` (it changes).
    partition_key: Optional[str] = "created_at"
    # Server-side time filter param, only set where the API genuinely filters (see settings below).
    incremental_filter_param: Optional[str] = None
    # Sort value passed to keep pagination ordering stable/monotonic.
    sort: Optional[str] = None
    # Set when the endpoint is scoped to one parent resource and has to be fanned out over it.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out helper for the `count` param and the incremental cursor.
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None


CALENDLY_ENDPOINTS: dict[str, CalendlyEndpointConfig] = {
    "event_types": CalendlyEndpointConfig(
        name="event_types",
        path="/event_types",
    ),
    # The only endpoint with a real server-side timestamp filter (`min_start_time`). It filters on
    # `start_time` (the scheduled meeting time), so incremental syncs advance on `start_time`, not on
    # created/updated. Late-created events with a `start_time` below the watermark can be missed; the
    # merge dedupes on `uri` for everything re-fetched. Partitioning stays on the stable `created_at`.
    "scheduled_events": CalendlyEndpointConfig(
        name="scheduled_events",
        path="/scheduled_events",
        incremental_filter_param="min_start_time",
        sort="start_time:asc",
        default_incremental_field="start_time",
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Fanned out over `scheduled_events`: the invitee is the person who booked the meeting, with
    # their answers, tracking and cancellation. The endpoint takes no organization param and no
    # server-side time filter, so every sync re-reads each event's invitees and merges on `uri`.
    "invitees": CalendlyEndpointConfig(
        name="invitees",
        path="/scheduled_events/{uuid}/invitees",
        scope_param=None,
        sort="created_at:asc",
        fanout=DependentEndpointConfig(
            parent_name="scheduled_events",
            resolve_param="uuid",
            resolve_field=PARENT_UUID_FIELD,
            # The invitee row already carries `event`, the parent's URI — nothing to copy down.
            include_from_parent=[],
        ),
    ),
    "groups": CalendlyEndpointConfig(
        name="groups",
        path="/groups",
    ),
    "organization_memberships": CalendlyEndpointConfig(
        name="organization_memberships",
        path="/organization_memberships",
    ),
    "routing_forms": CalendlyEndpointConfig(
        name="routing_forms",
        path="/routing_forms",
    ),
    # Fanned out over `routing_forms`. The parent URI rides in a query param rather than the path,
    # which the fan-out helper only binds through a `{placeholder}`, hence the query in `path`.
    "routing_form_submissions": CalendlyEndpointConfig(
        name="routing_form_submissions",
        path="/routing_form_submissions?form={form}",
        scope_param=None,
        sort="created_at:asc",
        fanout=DependentEndpointConfig(
            parent_name="routing_forms",
            resolve_param="form",
            resolve_field=PARENT_URI_PARAM_FIELD,
            # The submission row already carries `routing_form`, the parent's URI.
            include_from_parent=[],
        ),
    ),
    # Calendly calls these event type hosts; the path is `/event_type_memberships`. Fanned out over
    # `event_types`, and the only list endpoint here that accepts no `sort` param.
    "event_type_memberships": CalendlyEndpointConfig(
        name="event_type_memberships",
        path="/event_type_memberships?event_type={event_type}",
        scope_param=None,
        fanout=DependentEndpointConfig(
            parent_name="event_types",
            resolve_param="event_type",
            resolve_field=PARENT_URI_PARAM_FIELD,
            # The membership row embeds the whole parent event type object.
            include_from_parent=[],
        ),
    ),
    # Account-scoped: `/contacts` takes no `organization` param, unlike every other table here.
    "contacts": CalendlyEndpointConfig(
        name="contacts",
        path="/contacts",
        scope_param=None,
        sort="created_at:asc",
    ),
}

ENDPOINTS = tuple(CALENDLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CALENDLY_ENDPOINTS.items()
}

# Calendly only emits webhooks for invitee lifecycle and routing form submissions. The invitee
# payloads embed the whole `scheduled_event` object under the same field names the REST list
# endpoint returns, so those deliveries can merge straight into `scheduled_events`. Nothing else
# we sync has a matching event: there is no event type for event types, groups or memberships,
# and `routing_form_submission.created` carries a submission rather than the form we sync.
CALENDLY_WEBHOOK_EVENTS = ("invitee.created", "invitee.canceled")

# Key the hog template routes on, not a Calendly event name: both subscribed events map to the
# one table, so the template routes on the resource it found in the payload rather than on
# `body.event`.
WEBHOOK_RESOURCE_MAP: dict[str, str] = {"scheduled_events": "scheduled_event"}

WEBHOOK_SCHEMA_NAMES = tuple(WEBHOOK_RESOURCE_MAP)
