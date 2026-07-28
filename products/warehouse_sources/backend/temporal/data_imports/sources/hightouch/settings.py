from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

HIGHTOUCH_BASE_URL = "https://api.hightouch.com/api/v1"

# Hightouch list endpoints document `limit` with a default of 100; no higher cap is documented.
PAGE_SIZE = 100

# Sync runs keep mutating after they start (status, finishedAt, row counts), and the `after`
# filter selects on startedAt — so each incremental sync re-reads a trailing window and the
# merge refreshes runs that were still in progress when we first saw them.
SYNC_RUNS_LOOKBACK_SECONDS = 24 * 60 * 60

STARTED_AT_INCREMENTAL: IncrementalField = {
    "label": "startedAt",
    "type": IncrementalFieldType.DateTime,
    "field": "startedAt",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class HightouchEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = PAGE_SIZE
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # Response fields dropped from every row before it is yielded. Hightouch `configuration`
    # objects carry connection details (database credentials on sources, hostnames/usernames
    # and API secrets on destinations, custom auth headers on HTTP-destination syncs), which
    # must not be copied into warehouse tables any project member can query.
    strip_fields: tuple[str, ...] = ()


HIGHTOUCH_ENDPOINTS: dict[str, HightouchEndpointConfig] = {
    # Config tables (syncs, models, sources, destinations) have no server-side timestamp
    # filter — `after`/`before` on /syncs select by last-run time, not updatedAt — so they
    # stay full refresh. They are small (workspace configuration), so this is cheap.
    "syncs": HightouchEndpointConfig(
        name="syncs",
        path="/syncs",
        strip_fields=("configuration",),
    ),
    "sync_runs": HightouchEndpointConfig(
        name="sync_runs",
        path="/syncs/{sync_id}/runs",
        # `after` is a genuine server-side filter on startedAt, so incremental sync reduces
        # the pages fetched instead of just changing the write disposition.
        incremental_fields=[STARTED_AT_INCREMENTAL],
        default_incremental_field="startedAt",
        # createdAt is fixed at run creation, so it is a stable partition key (startedAt is
        # too, but createdAt exists on every run even before it starts).
        partition_key="createdAt",
        # The run id is only documented per sync, and this table aggregates runs across every
        # sync, so the parent sync id is part of the key to keep it unique table-wide.
        primary_key=["sync_id", "id"],
        # Fan-out interleaves parents, so rows are never globally ascending by startedAt even
        # if each sync's runs were: desc mode makes the pipeline persist the incremental
        # watermark only when a sync completes, so a partial run can't advance the watermark
        # past runs of syncs it never reached.
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="syncs",
            resolve_param="sync_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sync_id"},
            # `orderBy=id` pins a strictly monotonic, unique sort so offset pages don't skip
            # or duplicate rows if the API's implicit ordering shifts while rows are inserted
            # mid-walk (Hightouch documents orderBy fields but not the direction).
            parent_params={"orderBy": "id"},
        ),
    ),
    "models": HightouchEndpointConfig(
        name="models",
        path="/models",
    ),
    "sources": HightouchEndpointConfig(
        name="sources",
        path="/sources",
        strip_fields=("configuration",),
    ),
    "destinations": HightouchEndpointConfig(
        name="destinations",
        path="/destinations",
        strip_fields=("configuration",),
    ),
}

ENDPOINTS = tuple(HIGHTOUCH_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HIGHTOUCH_ENDPOINTS.items()
}
