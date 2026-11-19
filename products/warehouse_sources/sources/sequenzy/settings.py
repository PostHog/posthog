from dataclasses import field
from datetime import timedelta
from typing import Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

SEQUENZY_BASE_URL = "https://api.sequenzy.com/api/v1"

EMAIL_SENDS_RETENTION_DAYS = 14

# The event endpoints reject a `start`/`end` range longer than 90 days. Stay just inside it.
EVENTS_MAX_WINDOW = timedelta(days=89, hours=23)

# Both event endpoints return delivery events only unless asked for every type.
ALL_EMAIL_EVENT_TYPES = "send,delivery,bounce,complaint,open,click,unsubscribe,delivery_delay,transport_failure"


@frozen
class SequenzyEndpointConfig:
    name: str
    path: str
    # Key of the row array in the response envelope ({"success": true, "<selector>": [...]}).
    data_selector: str
    pagination: Literal["cursor", "offset", "page", "single_page"]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str | None = None
    page_size: int = 100
    params: dict[str, str | int] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    event_time_range: bool = False
    resume_pages: bool = True
    fanout: DependentEndpointConfig | None = None
    sort_mode: Literal["asc", "desc"] | None = "desc"


def _datetime_field(name: str) -> IncrementalField:
    return IncrementalField(
        label=name,
        type=IncrementalFieldType.DateTime,
        field=name,
        field_type=IncrementalFieldType.DateTime,
    )


# Sequenzy paginates each collection differently: subscribers use an opaque cursor
# (`pagination.nextCursor`), campaigns, sequences, and enrollments use limit/offset, per-email
# metrics, email sends, and events use page numbers, and the small definition collections
# (tags, lists, segments) return the whole collection in one response. Subscribers, campaigns,
# and sequences are returned newest-first with no way to request ascending order, hence the
# default sort_mode="desc".
ENDPOINTS_CONFIG: dict[str, SequenzyEndpointConfig] = {
    "subscribers": SequenzyEndpointConfig(
        name="subscribers",
        path="/subscribers",
        data_selector="subscribers",
        pagination="cursor",
        page_size=1000,
        # `status=all` disables the default status filter so unsubscribed and bounced
        # contacts sync too. `includeTotal=false` skips the total-count query the API
        # otherwise runs for the first (cursorless) request.
        params={"status": "all", "includeTotal": "false"},
        partition_key="createdAt",
    ),
    "tags": SequenzyEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="tags",
        pagination="single_page",
    ),
    "lists": SequenzyEndpointConfig(
        name="lists",
        path="/lists",
        data_selector="lists",
        pagination="single_page",
    ),
    "segments": SequenzyEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
        pagination="single_page",
    ),
    "campaigns": SequenzyEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        pagination="offset",
        page_size=100,
        partition_key="createdAt",
    ),
    "sequences": SequenzyEndpointConfig(
        name="sequences",
        path="/sequences",
        data_selector="sequences",
        pagination="offset",
        page_size=100,
        partition_key="createdAt",
    ),
    "email_metrics": SequenzyEndpointConfig(
        name="email_metrics",
        path="/metrics/emails",
        data_selector="emails",
        pagination="page",
        page_size=500,
        # The default sort is `sent` desc, which reshuffles rows between pages as counts
        # move mid-sync. Name order is the most stable sort the endpoint offers.
        params={"sort": "name", "order": "asc"},
        # `emailId` is a campaign ID for campaign rows and an automation node ID for
        # sequence-step rows; the composite key guards against a collision across the
        # two ID namespaces.
        primary_keys=["emailType", "emailId"],
    ),
    "email_sends": SequenzyEndpointConfig(
        name="email_sends",
        path="/email-sends",
        data_selector="emailSends",
        pagination="page",
        page_size=100,
        # A send's status changes after `createdAt`, so every run reads the whole retained
        # window and the merge updates older rows.
        params={"days": EMAIL_SENDS_RETENTION_DAYS, "sortField": "createdAt", "sortOrder": "asc"},
        partition_key="createdAt",
        incremental_fields=[_datetime_field("createdAt")],
        default_incremental_field="createdAt",
        # The `days` window counts back from the server's clock, so a page number saved by one
        # attempt points at other rows on the next.
        resume_pages=False,
        sort_mode=None,
    ),
    "campaign_events": SequenzyEndpointConfig(
        name="campaign_events",
        path="/metrics/campaigns/{campaignId}/events",
        data_selector="events",
        pagination="page",
        page_size=500,
        params={"eventTypes": ALL_EMAIL_EVENT_TYPES},
        primary_keys=["campaignId", "id"],
        partition_key="eventTime",
        incremental_fields=[_datetime_field("eventTime")],
        default_incremental_field="eventTime",
        event_time_range=True,
        fanout=DependentEndpointConfig(
            parent_name="campaigns",
            resolve_param="campaignId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "campaignId"},
        ),
        sort_mode=None,
    ),
    "sequence_events": SequenzyEndpointConfig(
        name="sequence_events",
        path="/metrics/sequences/{sequenceId}/events",
        data_selector="events",
        pagination="page",
        page_size=500,
        params={"eventTypes": ALL_EMAIL_EVENT_TYPES},
        # An event's `campaignId` holds the sequence email step here, so the parent sequence
        # rides along as `sequenceId`.
        primary_keys=["sequenceId", "id"],
        partition_key="eventTime",
        incremental_fields=[_datetime_field("eventTime")],
        default_incremental_field="eventTime",
        event_time_range=True,
        fanout=DependentEndpointConfig(
            parent_name="sequences",
            resolve_param="sequenceId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sequenceId"},
        ),
        sort_mode=None,
    ),
    "sequence_enrollments": SequenzyEndpointConfig(
        name="sequence_enrollments",
        path="/sequences/{sequenceId}/enrollments",
        data_selector="enrollments",
        pagination="offset",
        page_size=500,
        # The default status filter returns only contacts still in the sequence.
        params={"status": "active,waiting,paused,completed,failed,cancelled", "sort": "enrolled_at_asc"},
        primary_keys=["sequenceId", "enrollmentId"],
        partition_key="enrollmentStartedAt",
        fanout=DependentEndpointConfig(
            parent_name="sequences",
            resolve_param="sequenceId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sequenceId"},
        ),
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

# The API expires email sends and events, so these tables merge to keep older rows. The other
# list endpoints have no created/updated filter, so they are full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS_CONFIG.items() if config.incremental_fields
}

# A re-read window overlaps rows that were already synced, so append would duplicate them.
MERGE_ONLY_ENDPOINTS = tuple(INCREMENTAL_FIELDS.keys())
