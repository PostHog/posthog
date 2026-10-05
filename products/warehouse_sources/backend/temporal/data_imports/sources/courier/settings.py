from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

COURIER_BASE_URL = "https://api.courier.com"

# Courier's REST API is unversioned on the wire: one https://api.courier.com host, Bearer auth, and
# no version header or path segment (per the vendor API reference). "1.0.0" and "2.0.0" are
# documentation-site labels — the 1.0.0 reference now redirects to 2.0.0. UNVERSIONED_API_VERSION
# ("v1") is the framework placeholder pre-versioning rows carry, and it already hits the same live
# API the 2.0.0 docs describe. Both labels therefore resolve to identical requests, so nothing
# branches on the version — these are declared for source pinning and the default only.
COURIER_API_VERSION_2_0_0 = "2.0.0"
SUPPORTED_VERSIONS = (UNVERSIONED_API_VERSION, COURIER_API_VERSION_2_0_0)
DEFAULT_VERSION = COURIER_API_VERSION_2_0_0

# Courier's default page size is small (~10 messages/page per the vendor docs); raising `limit`
# cuts the round-trips a full backfill needs. No documented maximum, so we stay conservative.
COURIER_PAGE_SIZE = 100


@dataclass(frozen=True)
class CourierEndpointConfig:
    name: str
    path: str
    # The list of records is wrapped under a named key that varies per endpoint ("results" vs
    # "items").
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Request param carrying the server-side lower-bound timestamp filter.
    incremental_param: str | None = None
    # Stable datetime field to partition on; None disables partitioning.
    partition_key: str | None = None
    # Courier's list endpoints document no explicit sort param at all. Treated as newest-first
    # (matching Knock's identical no-sort-param message-log endpoint) rather than assumed
    # ascending, which would silently corrupt the incremental watermark if wrong.
    sort_mode: SortMode = "asc"
    # Where the paginator finds the next-page cursor in the response body: nested under `paging`
    # for every list endpoint except Tenants, which returns `cursor` at the top level.
    cursor_path: str = "paging.cursor"
    # Fields that arrive as epoch-millisecond ints or ISO-8601 strings and are converted to real
    # datetimes before yielding, so partitioning and incremental filtering see proper timestamps
    # instead of raw millis (which the partitioner would otherwise misread as epoch seconds).
    timestamp_fields: tuple[str, ...] = ()
    page_size: int = COURIER_PAGE_SIZE
    # False where the endpoint returns every record in one response and takes no cursor.
    paginated: bool = True
    # False where a missing `data_selector` key is a legitimate empty response rather than an
    # envelope change worth failing the sync over.
    data_selector_required: bool = True
    # Set where the endpoint only exists per parent record, so rows are collected by walking the
    # parent listing first.
    fanout: DependentEndpointConfig | None = None
    # Page-size param the fan-out sends to both its parent and child listing. None for a parent
    # that documents no page-size param at all; the child then carries its own in `child_params`.
    fanout_page_size_param: str | None = "limit"
    # Where a fan-out child finds its own next-page cursor, when that differs from the parent's
    # `cursor_path`. One paginator config is shared by both halves of a fan-out otherwise.
    child_cursor_path: str | None = None
    # Parent field percent-encoded into the fan-out's `resolve_field` before the child path is
    # bound, for an id that can contain a literal "/".
    encode_parent_field: str | None = None
    # Filter param on the *parent* listing, for a fan-out child whose own endpoint takes no
    # timestamp filter. Bounding the parent walk is the only way such a child can sync
    # incrementally instead of re-fetching every parent's records every run.
    parent_incremental_param: str | None = None

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


# Parent listings a fan-out endpoint walks that are not themselves syncable tables.
FANOUT_ONLY_CONFIGS: dict[str, CourierEndpointConfig] = {
    # Digest schedules have no listing endpoint of their own: Courier only exposes a schedule id
    # nested inside the digest config of a workspace preference's topics, so they are flattened
    # out of the one unpaginated preferences response. A workspace with no digest configured
    # matches nothing here, which is why the selector is not required.
    "DigestSchedules": CourierEndpointConfig(
        name="DigestSchedules",
        path="/preferences/sections",
        data_selector="results[*].topics[*].digest.schedules[*]",
        data_selector_required=False,
    ),
}

ENDPOINTS_CONFIG: dict[str, CourierEndpointConfig] = {
    # The primary stream: per-message delivery status/history. `enqueued_after` is a documented
    # server-side filter, so incremental sync genuinely reduces pages.
    "Messages": CourierEndpointConfig(
        name="Messages",
        path="/messages",
        data_selector="results",
        primary_keys=("id",),
        incremental_fields=[incremental_field("enqueued")],
        incremental_param="enqueued_after",
        partition_key="enqueued",
        sort_mode="desc",
        timestamp_fields=("enqueued", "sent", "delivered", "opened", "clicked"),
    ),
    # Per-message state transitions (enqueued, sent, delivered, opened, clicked). The Messages
    # row only carries the end state, so this is where the deliverability funnel lives.
    "MessageHistory": CourierEndpointConfig(
        name="MessageHistory",
        path="/messages/{message_id}/history",
        data_selector="results",
        # Courier types the entries as free-form objects. `type` is the endpoint's own filter
        # param and the response is documented as one entry per status transition with its
        # timestamp, so the transition and its `ts` are what identifies a row within a message.
        primary_keys=("message_id", "type", "ts"),
        # Projected from the parent message, because the entries carry no timestamp Courier can
        # filter on. See `parent_incremental_param`.
        incremental_fields=[incremental_field("enqueued")],
        parent_incremental_param="enqueued_after",
        partition_key="enqueued",
        sort_mode="desc",
        timestamp_fields=("ts", "enqueued"),
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="Messages",
            resolve_param="message_id",
            resolve_field="id",
            include_from_parent=["id", "enqueued"],
            parent_field_renames={"id": "message_id", "enqueued": "enqueued"},
            # A message archived or aged out of log retention between the listing and this
            # fetch 404s; that parent is skipped rather than failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # Account activity log. No server-side timestamp filter is documented, so full refresh only.
    "AuditEvents": CourierEndpointConfig(
        name="AuditEvents",
        path="/audit-events",
        data_selector="results",
        primary_keys=("auditEventId",),
        partition_key="timestamp",
        timestamp_fields=("timestamp",),
    ),
    # Saved recipient segments. No server-side timestamp filter is documented.
    "Audiences": CourierEndpointConfig(
        name="Audiences",
        path="/audiences",
        data_selector="items",
        primary_keys=("id",),
        partition_key="created_at",
        timestamp_fields=("created_at", "updated_at"),
    ),
    # Who currently matches each audience filter. Courier recalculates membership as profiles
    # change and exposes no timestamp filter, so full refresh only.
    "AudienceMembers": CourierEndpointConfig(
        name="AudienceMembers",
        path="/audiences/{audience_id}/members",
        data_selector="items",
        # `member_id` is the user, unique only within its audience. Each row already carries its
        # own `audience_id`, so nothing has to be projected from the parent to key it.
        primary_keys=("audience_id", "member_id"),
        partition_key="added_at",
        timestamp_fields=("added_at",),
        fanout=DependentEndpointConfig(
            parent_name="Audiences",
            resolve_param="audience_id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    # Branding profiles (templates/colors/logos). No server-side timestamp filter, and the
    # `created`/`updated` unix timestamps are undocumented as to unit, so no partitioning.
    "Brands": CourierEndpointConfig(
        name="Brands",
        path="/brands",
        data_selector="results",
        primary_keys=("id",),
    ),
    # The recipient groups every list-targeted send resolves through. No server-side timestamp
    # filter, so full refresh only.
    "Lists": CourierEndpointConfig(
        name="Lists",
        path="/lists",
        data_selector="items",
        primary_keys=("id",),
        partition_key="created",
        timestamp_fields=("created", "updated"),
    ),
    # Who is subscribed to each list. Courier documents no timestamp filter on either the list
    # walk or the subscriptions, so full refresh only.
    "ListSubscriptions": CourierEndpointConfig(
        name="ListSubscriptions",
        path="/lists/{list_id}/subscriptions",
        data_selector="items",
        # The subscription carries the recipient but no reference back to its list, so the
        # parent's id is projected in to make rows joinable and unique across lists.
        primary_keys=("list_id", "recipientId"),
        partition_key="created",
        timestamp_fields=("created",),
        fanout=DependentEndpointConfig(
            parent_name="Lists",
            resolve_param="list_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "list_id"},
            # A list deleted between the listing and this fetch 404s; skip that parent rather
            # than failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # The template catalog resolving the `notification` id every message carries. Like Brands,
    # `created_at`/`updated_at` are int64s of undocumented unit, so no partitioning.
    "NotificationTemplates": CourierEndpointConfig(
        name="NotificationTemplates",
        path="/notifications",
        data_selector="results",
        primary_keys=("id",),
    ),
    # Multi-tenant scoping objects. No timestamp fields at all, so no partitioning.
    "Tenants": CourierEndpointConfig(
        name="Tenants",
        path="/tenants",
        data_selector="items",
        primary_keys=("id",),
        cursor_path="cursor",
    ),
    # Who belongs to each tenant, which is who a tenant-scoped send reaches. The association
    # carries no timestamp, so full refresh only.
    "TenantUsers": CourierEndpointConfig(
        name="TenantUsers",
        path="/tenants/{tenant_id}/users",
        data_selector="items",
        # The association repeats its own `tenant_id`, but a user belongs to many tenants, so the
        # parent's id is projected in as well rather than trusting an optional field to key rows.
        primary_keys=("tenant_id", "user_id"),
        cursor_path="cursor",
        fanout=DependentEndpointConfig(
            parent_name="Tenants",
            resolve_param="tenant_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "tenant_id"},
            # A tenant deleted between the listing and this fetch 404s; skip that parent rather
            # than failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # The flow definitions a message is attributed to. Returns the published version of each
    # journey; no server-side timestamp filter, so full refresh only.
    "Journeys": CourierEndpointConfig(
        name="Journeys",
        path="/journeys",
        data_selector="templates",
        primary_keys=("id",),
        partition_key="createdAt",
        timestamp_fields=("createdAt", "updatedAt"),
        cursor_path="cursor",
    ),
    # Each journey's publish history, for comparing performance across versions.
    "JourneyVersions": CourierEndpointConfig(
        name="JourneyVersions",
        path="/journeys/{templateId}/versions",
        data_selector="results",
        # The version entry carries no reference back to its journey, so the parent's id is
        # projected in to make rows joinable and unique across journeys.
        primary_keys=("journey_id", "version"),
        partition_key="created",
        timestamp_fields=("created", "published"),
        # The parent /journeys walk finds its cursor at the top level; this endpoint nests its
        # own under `paging`.
        cursor_path="cursor",
        child_cursor_path="paging.cursor",
        fanout=DependentEndpointConfig(
            parent_name="Journeys",
            resolve_param="templateId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "journey_id"},
            # A journey archived between the listing and this fetch 404s; skip that parent
            # rather than failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # What each digest schedule has accumulated per user, explaining why messages were batched or
    # held back. No server-side timestamp filter, so full refresh only.
    "DigestInstances": CourierEndpointConfig(
        name="DigestInstances",
        path="/digests/schedules/{schedule_id}/instances",
        data_selector="items",
        # `digest_instance_id` is documented as unique to the instance, but an instance only
        # exists within its schedule, so the schedule is part of the key.
        primary_keys=("schedule_id", "digest_instance_id"),
        partition_key="created_at",
        timestamp_fields=("created_at",),
        cursor_path="cursor",
        encode_parent_field="schedule_id",
        # The preferences listing the schedule ids come from takes no params at all.
        fanout_page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="DigestSchedules",
            resolve_param="schedule_id",
            resolve_field="encoded_schedule_id",
            include_from_parent=["schedule_id"],
            parent_field_renames={"schedule_id": "schedule_id"},
            child_params={"limit": COURIER_PAGE_SIZE},
            # A schedule removed between the preferences read and this fetch 404s; skip it
            # rather than failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

# Every config a fan-out can resolve a parent against, syncable or not.
FANOUT_ENDPOINT_CONFIGS: dict[str, CourierEndpointConfig] = {**ENDPOINTS_CONFIG, **FANOUT_ONLY_CONFIGS}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS_CONFIG.items()
}
