from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class RenderEndpointConfig:
    name: str
    # Path relative to the API base. Fan-out children use a `{parent_id}` placeholder
    # (or `parent_query_param` when the parent id is passed as a query param instead).
    path: str
    # Key the resource is nested under in each list item (Render wraps every item as
    # `{"<wrapper_key>": {...}, "cursor": "..."}` — the cursor is a sibling of the resource).
    wrapper_key: str
    # Primary key columns for dedup. Fan-out children include the parent id: Render ids carry
    # unique prefixes (dep-, job-, evt-) but global uniqueness isn't documented, and a
    # non-unique key would multi-match on every delta merge.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Incremental field name -> server-side "after" query param (e.g. updatedAt -> updatedAfter).
    # Only fields with a genuine server-side filter are advertised as incremental options.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: str | None = None
    # Stable datetime field to partition by (createdAt-style, never updatedAt).
    partition_key: str | None = None
    # Fan-out: name of the parent endpoint whose rows seed this child's requests.
    parent: str | None = None
    # Pass the parent id as this query param instead of a `{parent_id}` path placeholder.
    parent_query_param: str | None = None
    # Column to copy the parent id onto child rows that don't carry it themselves
    # (deploys and custom domains omit the service id from their payloads).
    inject_parent_key: str | None = None
    # Whether the endpoint accepts the `ownerId` filter (used to scope a multi-workspace key).
    supports_owner_filter: bool = False
    # Rows are immutable (events): append-only is the only incremental-style sync mode.
    append_only: bool = False
    # Fallback lower bound for endpoints whose time window defaults server-side to a recent
    # slice (events default to the last hour) — read from this parent field when no
    # incremental watermark applies, so a full refresh still covers the parent's lifetime.
    window_start_from_parent_field: str | None = None
    should_sync_default: bool = True
    page_size: int = 100
    # Hard cap on pages fetched per parent in a fan-out, to bound runaway pagination.
    # A structured warning is logged if the cap is reached.
    max_pages_per_parent: int = 500
    # Some endpoints return secrets the API key is only meant to *use* for sync (env var
    # values, secret-file contents), not data worth warehousing. Maps a list column to the
    # item keys whose values are redacted before a row is yielded, keeping the safe metadata
    # (names, keys, ids). Any endpoint with entries here is treated as sensitive: its raw
    # responses are also excluded from HTTP sample capture (see `is_sensitive`).
    redact_list_item_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def is_sensitive(self) -> bool:
        return bool(self.redact_list_item_fields)


RENDER_ENDPOINTS: dict[str, RenderEndpointConfig] = {
    "owners": RenderEndpointConfig(
        name="owners",
        path="/owners",
        wrapper_key="owner",
        # No timestamps on the owner object and no time filters on the endpoint: full refresh only.
    ),
    "projects": RenderEndpointConfig(
        name="projects",
        path="/projects",
        wrapper_key="project",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        supports_owner_filter=True,
    ),
    "environments": RenderEndpointConfig(
        name="environments",
        path="/environments",
        wrapper_key="environment",
        # The environment object carries no timestamps, so there is no watermark column to
        # sync incrementally on despite the endpoint's updatedBefore/After filters.
        primary_keys=["projectId", "id"],
        parent="projects",
        parent_query_param="projectId",
    ),
    "services": RenderEndpointConfig(
        name="services",
        path="/services",
        wrapper_key="service",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        partition_key="createdAt",
        supports_owner_filter=True,
    ),
    "deploys": RenderEndpointConfig(
        name="deploys",
        path="/services/{parent_id}/deploys",
        wrapper_key="deploy",
        primary_keys=["serviceId", "id"],
        incremental_fields=[
            _datetime_field("finishedAt"),
            _datetime_field("updatedAt"),
            _datetime_field("createdAt"),
        ],
        incremental_param_by_field={
            "finishedAt": "finishedAfter",
            "updatedAt": "updatedAfter",
            "createdAt": "createdAfter",
        },
        # finishedAt: in-flight deploys (null finishedAt) are excluded by finishedAfter and
        # picked up once they reach a terminal state, so each deploy lands exactly once with
        # its final status — the right grain for deploy analytics.
        default_incremental_field="finishedAt",
        partition_key="createdAt",
        parent="services",
        inject_parent_key="serviceId",
    ),
    "jobs": RenderEndpointConfig(
        name="jobs",
        path="/services/{parent_id}/jobs",
        wrapper_key="job",
        primary_keys=["serviceId", "id"],
        incremental_fields=[
            _datetime_field("finishedAt"),
            _datetime_field("startedAt"),
            _datetime_field("createdAt"),
        ],
        incremental_param_by_field={
            "finishedAt": "finishedAfter",
            "startedAt": "startedAfter",
            "createdAt": "createdAfter",
        },
        default_incremental_field="finishedAt",
        partition_key="createdAt",
        parent="services",
    ),
    "events": RenderEndpointConfig(
        name="events",
        path="/services/{parent_id}/events",
        wrapper_key="event",
        primary_keys=["serviceId", "id"],
        incremental_fields=[_datetime_field("timestamp")],
        incremental_param_by_field={"timestamp": "startTime"},
        default_incremental_field="timestamp",
        partition_key="timestamp",
        parent="services",
        append_only=True,
        # The events window defaults to the last hour server-side, so every request must pass
        # an explicit startTime; events can't predate their service, so its createdAt is a
        # complete lower bound for full refreshes and first syncs.
        window_start_from_parent_field="createdAt",
    ),
    "custom_domains": RenderEndpointConfig(
        name="custom_domains",
        path="/services/{parent_id}/custom-domains",
        wrapper_key="customDomain",
        primary_keys=["serviceId", "id"],
        # Only createdBefore/After filters exist, but verificationStatus mutates after
        # creation — a createdAt cursor would freeze it. Tiny table: full refresh only.
        parent="services",
        inject_parent_key="serviceId",
    ),
    "env_groups": RenderEndpointConfig(
        name="env_groups",
        path="/env-groups",
        # The docs show env group list items unwrapped (no cursor sibling); the transport
        # falls back to treating the item as the row when the wrapper key is absent.
        wrapper_key="envGroup",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        supports_owner_filter=True,
        # The list response embeds env var values and secret-file contents (database URLs, API
        # tokens, …). Redact the value-bearing fields so only names/keys/ids reach the warehouse.
        redact_list_item_fields={"envVars": ("value",), "secretFiles": ("content", "contents")},
    ),
    "postgres": RenderEndpointConfig(
        name="postgres",
        path="/postgres",
        wrapper_key="postgres",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        supports_owner_filter=True,
    ),
    "key_value": RenderEndpointConfig(
        name="key_value",
        path="/key-value",
        wrapper_key="keyValue",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        supports_owner_filter=True,
    ),
    "disks": RenderEndpointConfig(
        name="disks",
        path="/disks",
        wrapper_key="disk",
        incremental_fields=[_datetime_field("updatedAt"), _datetime_field("createdAt")],
        incremental_param_by_field={"updatedAt": "updatedAfter", "createdAt": "createdAfter"},
        default_incremental_field="updatedAt",
        supports_owner_filter=True,
    ),
}

ENDPOINTS = tuple(RENDER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RENDER_ENDPOINTS.items()
}
