from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# How an endpoint paginates. Codefresh is inconsistent across resources:
#   - "offset": limit/offset query params, terminate when a page is short (projects, pipelines,
#               images, step_types, environments)
#   - "page":   1-indexed `page` param plus a `pagination.nextPage` flag and a stable `sessionId` cursor (builds)
#   - "none":   single request, no pagination params (triggers, teams, users)
PaginationMode = Literal["offset", "page", "none"]

# Placeholder substituted with the account id before an endpoint path is requested. Codefresh
# publishes no endpoint that reports the account a key belongs to, so the id is resolved at sync
# time (see ``_resolve_account_id``).
ACCOUNT_ID_PLACEHOLDER = "{account_id}"


@dataclass(frozen=True)
class CodefreshEndpointConfig:
    name: str
    path: str
    pagination: PaginationMode
    # Path to the list of records inside the response body. ``None`` means the body is itself a bare
    # array. Otherwise it's the sequence of keys to walk (e.g. ["docs"] or ["workflows", "docs"]).
    data_key: Optional[list[str]] = None
    # Nested object whose fields are lifted to the row's top level (e.g. pipeline `metadata`), so the
    # primary key / partition columns resolve against real top-level fields.
    flatten_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Never an `updated`/`lastSeen` field — those rewrite
    # partitions on every sync. ``None`` when the resource exposes no stable creation timestamp.
    partition_key: Optional[str] = None
    page_size: int = 100
    should_sync_default: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Fail loud when the configured ``data_key`` is absent from a 200 body, instead of syncing zero
    # rows. Set it where the vendor does not document the response envelope, so a wrong guess or a
    # later shape change is visible. Bare-array endpoints (``data_key`` is ``None``) always fail loud.
    require_data_key: bool = False
    # Fields to strip from every row before it's emitted, to keep secret-bearing fields (e.g. a
    # project's `variables` or a pipeline's `spec.variables`, which can hold plaintext config values)
    # out of the warehouse, where any table reader could see them. Each entry is a dotted path, so
    # nested fields can be redacted (e.g. `spec.variables`); a bare name targets a top-level field.
    redact_keys: list[str] = field(default_factory=list)


CODEFRESH_ENDPOINTS: dict[str, CodefreshEndpointConfig] = {
    "projects": CodefreshEndpointConfig(
        name="projects",
        path="/projects",
        pagination="offset",
        data_key=None,  # bare array
        primary_keys=["id"],
        # Project variables can hold plaintext secrets — never land them in the warehouse.
        redact_keys=["variables"],
    ),
    "pipelines": CodefreshEndpointConfig(
        name="pipelines",
        path="/pipelines",
        pagination="offset",
        data_key=["docs"],  # envelope: {docs: [...], count}
        flatten_key="metadata",  # lift metadata.{id,name,project,...} to the row top level
        primary_keys=["id"],
        # Pipeline spec variables are exported with their plaintext `value` — keep them out of the warehouse.
        redact_keys=["spec.variables"],
    ),
    "builds": CodefreshEndpointConfig(
        name="builds",
        path="/workflow",
        pagination="page",
        data_key=["workflows", "docs"],  # nested envelope: {workflows: {docs: [...]}, pagination: {...}}
        primary_keys=["id"],
        partition_key="created",
    ),
    "images": CodefreshEndpointConfig(
        name="images",
        path="/images",
        pagination="offset",
        data_key=None,  # bare array
        primary_keys=["id"],
        partition_key="created",
    ),
    "triggers": CodefreshEndpointConfig(
        name="triggers",
        path="/hermes/triggers",
        pagination="none",
        data_key=None,  # bare array, no pagination params
        # A trigger row is the link between a trigger-event and a pipeline; neither is unique on its
        # own across the table, so the pair is the key.
        primary_keys=["event", "pipeline"],
        # `event-data.secret` is the webhook signing secret, and `event-data.endpoint` embeds it as a
        # query parameter — keep both out of the warehouse where any table reader could recover them.
        redact_keys=["event-data.endpoint", "event-data.secret"],
    ),
    "step_types": CodefreshEndpointConfig(
        name="step_types",
        path="/step-types",
        pagination="offset",
        data_key=None,  # bare array
        primary_keys=["id"],
    ),
    "environments": CodefreshEndpointConfig(
        name="environments",
        path="/environments-v2",
        pagination="offset",
        # Codefresh does not document this response body. Its other undocumented list endpoints
        # wrap rows in a ``docs`` envelope, so that is what we read, and ``require_data_key`` turns
        # a wrong envelope into a loud failure instead of a table that syncs zero rows every run.
        data_key=["docs"],
        require_data_key=True,
        primary_keys=["_id"],
    ),
    "teams": CodefreshEndpointConfig(
        name="teams",
        path="/team",
        pagination="none",
        data_key=None,  # bare array, no pagination params
        primary_keys=["_id"],
    ),
    "users": CodefreshEndpointConfig(
        name="users",
        path=f"/accounts/{ACCOUNT_ID_PLACEHOLDER}/users",
        pagination="none",
        data_key=None,  # bare array, no pagination params
        primary_keys=["_id"],
        # An invite URL lets whoever holds it join the account, so it must stay out of the
        # warehouse where any table reader could recover it.
        redact_keys=["inviteUrl"],
    ),
}

ENDPOINTS = tuple(CODEFRESH_ENDPOINTS.keys())

# Codefresh has no server-side updated-since filter on any list endpoint, so no endpoint is genuinely
# incremental — every table is full refresh only. Kept as an (empty) per-endpoint map for parity with
# other sources and so the schema builder has a single place to read advertised fields from.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CODEFRESH_ENDPOINTS.items()
}
