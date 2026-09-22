from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.queries import (
    ASSET_MATERIALIZATIONS_QUERY,
    ASSET_NODES_QUERY,
    ASSET_OBSERVATIONS_QUERY,
    ASSETS_QUERY,
    BACKFILLS_QUERY,
    INSTIGATION_STATES_QUERY,
    INSTIGATION_TICKS_QUERY,
    REPOSITORIES_QUERY,
    RUNS_QUERY,
    SCHEDULES_QUERY,
    SENSORS_QUERY,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Dagster's runsOrError caps well below 100 in practice; 100 is a safe request size across the
# runs/backfills/assets list resolvers.
DAGSTER_CLOUD_PAGE_SIZE = 100

# "row" -> next cursor is a field read off the last result row (runId / backfill id).
# "connection" -> next cursor is the connection object's own `cursor` field (assetsOrError).
CursorMode = Literal["row", "connection"]

# Which collection a fan-out child iterates one request at a time.
ParentKind = Literal["repositories", "assets", "instigation_states"]

# Wire type of a windowed child's timestamp bounds: assetMaterializations/assetObservations take
# epoch milliseconds as a string, InstigationState.ticks takes epoch seconds as a float.
WindowUnit = Literal["millis_string", "seconds_float"]


def _incremental_datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
class DagsterCloudFanOutConfig:
    parent_kind: ParentKind
    # GraphQL variable name -> parent descriptor key. One request per parent.
    parent_variables: dict[str, str] = field(default_factory=dict)
    # Parent descriptor keys copied onto every child row. Fan-out children aggregate rows from
    # every parent, so the row has to carry its parent's identity for the primary key to stay
    # unique across the whole table.
    include_from_parent: list[str] = field(default_factory=list)
    # Batched form: one request per `batch_size` parents, collecting each parent's `batch_field`
    # into the `batch_variable` list. Mutually exclusive with `parent_variables`.
    batch_variable: str | None = None
    batch_field: str | None = None
    batch_size: int = 1
    # Windowed children have no cursor, so they page backwards: `before_variable` is set to the
    # oldest `window_row_field` value the previous page carried, and `after_variable` carries the
    # incremental watermark. Unset for children that return one unpaged list per parent.
    before_variable: str | None = None
    after_variable: str | None = None
    window_row_field: str | None = None
    window_unit: WindowUnit | None = None


@frozen
class DagsterCloudEndpointConfig:
    name: str
    query: str
    # Root query field wrapping the union result (e.g. "runsOrError").
    response_field: str
    # __typename of the success member of the OrError union, or None when the root field returns
    # the row list directly (assetNodes).
    success_typename: str | None = None
    # Key on the success member holding the list of rows ("results", "nodes", "ticks").
    results_key: str | None = None
    # __typename values meaning "this parent is gone" rather than "the sync failed". The parent
    # list is read before the children, so a parent deleted mid-sync must be skipped.
    skip_typenames: tuple[str, ...] = ()
    # Set for top-level endpoints paginated by a cursor; None for fan-out children.
    cursor_mode: CursorMode | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Row fields carrying Dagster epoch-seconds floats, normalized to ISO-8601 UTC strings so
    # datetime partitioning and the incremental watermark can read them like every other source.
    timestamp_fields: list[str] = field(default_factory=list)
    # Same, for row fields carrying epoch milliseconds as a string (the asset event resolvers).
    millis_timestamp_fields: list[str] = field(default_factory=list)
    # For cursor_mode="row": which row field to use as the next-page cursor.
    cursor_row_field: str | None = None
    fan_out: DagsterCloudFanOutConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    supports_incremental: bool = False
    # Stable creation-time field to partition by (never an updated-at style field).
    partition_key: str | None = None
    # runsOrError / partitionBackfillsOrError return newest-first with no ascending option, so the
    # rows genuinely arrive descending.
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True


DAGSTER_CLOUD_ENDPOINTS: dict[str, DagsterCloudEndpointConfig] = {
    "runs": DagsterCloudEndpointConfig(
        name="runs",
        query=RUNS_QUERY,
        response_field="runsOrError",
        success_typename="Runs",
        results_key="results",
        cursor_mode="row",
        cursor_row_field="runId",
        primary_keys=["runId"],
        timestamp_fields=["creationTime", "startTime", "endTime", "updateTime"],
        # RunsFilter.updatedAfter / .createdAfter are genuine server-side epoch filters, so an
        # incremental run only fetches runs changed since the watermark. updateTime is the default
        # (a run's status advances after creation); creationTime is offered for append-style pulls.
        incremental_fields=[
            _incremental_datetime_field("updateTime"),
            _incremental_datetime_field("creationTime"),
        ],
        supports_incremental=True,
        partition_key="creationTime",
        sort_mode="desc",
    ),
    "backfills": DagsterCloudEndpointConfig(
        name="backfills",
        query=BACKFILLS_QUERY,
        response_field="partitionBackfillsOrError",
        success_typename="PartitionBackfills",
        results_key="results",
        cursor_mode="row",
        cursor_row_field="id",
        primary_keys=["id"],
        timestamp_fields=["timestamp", "endTimestamp"],
        partition_key="timestamp",
        # partitionBackfillsOrError exposes only a status filter, no timestamp filter, so an
        # "incremental" pull would still walk full history every run — ship full refresh instead.
        sort_mode="desc",
    ),
    "assets": DagsterCloudEndpointConfig(
        name="assets",
        query=ASSETS_QUERY,
        response_field="assetsOrError",
        success_typename="AssetConnection",
        results_key="nodes",
        cursor_mode="connection",
        primary_keys=["id"],
        # Catalog snapshot with no timestamp to filter or partition on — full refresh.
    ),
    "schedules": DagsterCloudEndpointConfig(
        name="schedules",
        query=SCHEDULES_QUERY,
        response_field="schedulesOrError",
        success_typename="Schedules",
        results_key="results",
        skip_typenames=("RepositoryNotFoundError",),
        # Definition snapshot with no event timestamp — full refresh.
        primary_keys=["repositoryLocationName", "repositoryName", "name"],
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="repositories",
            parent_variables={
                "repositoryName": "repositoryName",
                "repositoryLocationName": "repositoryLocationName",
            },
            include_from_parent=["repositoryName", "repositoryLocationName"],
        ),
    ),
    "sensors": DagsterCloudEndpointConfig(
        name="sensors",
        query=SENSORS_QUERY,
        response_field="sensorsOrError",
        success_typename="Sensors",
        results_key="results",
        skip_typenames=("RepositoryNotFoundError",),
        primary_keys=["repositoryLocationName", "repositoryName", "name"],
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="repositories",
            parent_variables={
                "repositoryName": "repositoryName",
                "repositoryLocationName": "repositoryLocationName",
            },
            include_from_parent=["repositoryName", "repositoryLocationName"],
        ),
    ),
    "instigation_states": DagsterCloudEndpointConfig(
        name="instigation_states",
        query=INSTIGATION_STATES_QUERY,
        response_field="instigationStatesOrError",
        success_typename="InstigationStates",
        results_key="results",
        # A schedule and a sensor may share a name inside one repository, so the type belongs in
        # the key. repositoryName / repositoryLocationName are native fields on the row.
        primary_keys=["repositoryLocationName", "repositoryName", "instigationType", "name"],
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="repositories",
            parent_variables={"repositoryID": "repositoryId"},
        ),
    ),
    "instigation_ticks": DagsterCloudEndpointConfig(
        name="instigation_ticks",
        query=INSTIGATION_TICKS_QUERY,
        response_field="instigationStateOrError",
        success_typename="InstigationState",
        results_key="ticks",
        skip_typenames=("InstigationStateNotFoundError",),
        primary_keys=["instigationSelectorId", "tickId"],
        timestamp_fields=["timestamp", "endTimestamp"],
        # InstigationState.ticks takes a real afterTimestamp filter, so an incremental run only
        # fetches ticks newer than the watermark. A tick's timestamp never moves once written.
        incremental_fields=[_incremental_datetime_field("timestamp")],
        supports_incremental=True,
        partition_key="timestamp",
        # Rows arrive newest-first within a parent and in parent order across the fan-out, so the
        # stream is not ascending. "desc" also holds the watermark back until the whole fan-out
        # finished, which is the only safe point once rows stop arriving in time order.
        sort_mode="desc",
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="instigation_states",
            parent_variables={
                "repositoryName": "repositoryName",
                "repositoryLocationName": "repositoryLocationName",
                "instigationName": "instigationName",
                "instigationStateId": "instigationStateId",
            },
            include_from_parent=[
                "repositoryName",
                "repositoryLocationName",
                "instigationName",
                "instigationSelectorId",
            ],
            before_variable="beforeTimestamp",
            after_variable="afterTimestamp",
            window_row_field="timestamp",
            window_unit="seconds_float",
        ),
    ),
    "asset_nodes": DagsterCloudEndpointConfig(
        name="asset_nodes",
        query=ASSET_NODES_QUERY,
        response_field="assetNodes",
        # assetNodes returns [AssetNode!]! directly rather than an OrError union.
        primary_keys=["id"],
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="assets",
            # assetNodes with no argument would return every definition, with all its metadata, in
            # one unbounded response; batching the keys keeps each response a page-sized chunk.
            batch_variable="assetKeys",
            batch_field="assetKeyInput",
            batch_size=DAGSTER_CLOUD_PAGE_SIZE,
        ),
    ),
    "asset_materializations": DagsterCloudEndpointConfig(
        name="asset_materializations",
        query=ASSET_MATERIALIZATIONS_QUERY,
        response_field="assetOrError",
        success_typename="Asset",
        results_key="assetMaterializations",
        skip_typenames=("AssetNotFoundError",),
        # MaterializationEvent exposes no id, so the key is the event's natural identity. A run
        # step may report the same asset and partition more than once, and only the millisecond
        # timestamp separates those, so two reports inside one millisecond would collapse.
        primary_keys=["assetId", "runId", "timestamp", "partition", "stepKey"],
        millis_timestamp_fields=["timestamp"],
        # afterTimestampMillis is a genuine server-side filter on the event log.
        incremental_fields=[_incremental_datetime_field("timestamp")],
        supports_incremental=True,
        partition_key="timestamp",
        sort_mode="desc",
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="assets",
            parent_variables={"assetKeyPath": "assetKeyPath"},
            include_from_parent=["assetId"],
            before_variable="beforeTimestampMillis",
            after_variable="afterTimestampMillis",
            window_row_field="timestamp",
            window_unit="millis_string",
        ),
    ),
    "asset_observations": DagsterCloudEndpointConfig(
        name="asset_observations",
        query=ASSET_OBSERVATIONS_QUERY,
        response_field="assetOrError",
        success_typename="Asset",
        results_key="assetObservations",
        skip_typenames=("AssetNotFoundError",),
        primary_keys=["assetId", "runId", "timestamp", "partition", "stepKey"],
        millis_timestamp_fields=["timestamp"],
        incremental_fields=[_incremental_datetime_field("timestamp")],
        supports_incremental=True,
        partition_key="timestamp",
        sort_mode="desc",
        # Only observable source assets emit observations, and most deployments define none, so
        # syncing this by default would spend a full fan-out over every asset to find nothing.
        should_sync_default=False,
        fan_out=DagsterCloudFanOutConfig(
            parent_kind="assets",
            parent_variables={"assetKeyPath": "assetKeyPath"},
            include_from_parent=["assetId"],
            before_variable="beforeTimestampMillis",
            after_variable="afterTimestampMillis",
            window_row_field="timestamp",
            window_unit="millis_string",
        ),
    ),
}

ENDPOINTS = tuple(DAGSTER_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DAGSTER_CLOUD_ENDPOINTS.items()
}


# Not a synced table: the fan-out parent walk that resolves every code location + repository a
# schedule, sensor, instigation state or asset definition is scoped to.
REPOSITORIES_PARENT_CONFIG = DagsterCloudEndpointConfig(
    name="_repositories",
    query=REPOSITORIES_QUERY,
    response_field="repositoriesOrError",
    success_typename="RepositoryConnection",
    results_key="nodes",
)
