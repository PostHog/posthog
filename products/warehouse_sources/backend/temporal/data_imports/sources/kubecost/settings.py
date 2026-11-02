from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Default history pulled on the first sync. Days beyond the deployment's configured
# ETL retention return empty sets, so over-asking is harmless.
DEFAULT_BACKFILL_DAYS = 90
# Kubecost restates recent days as cloud-billing reconciliation lands, so incremental
# syncs re-pull a trailing window and merge on (key, window_start).
INCREMENTAL_LOOKBACK_DAYS = 3

_WINDOW_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "window_start",
        "type": IncrementalFieldType.DateTime,
        "field": "window_start",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class KubecostEndpointConfig:
    name: str
    path: str
    # Extra query params sent on every request (e.g. the Allocation API's `aggregate`).
    params: dict[str, str] = field(default_factory=dict)
    # Set when `data` is an object of `sets`, each holding its result set under this key
    # (Cloud Cost API), rather than a bare list of result sets (Allocation/Assets APIs).
    result_set_key: str | None = None
    # Set when `data.timeseries` holds windows whose line items sit in a list under this
    # key (External Costs API), rather than in result sets keyed by name.
    timeseries_items_key: str | None = None
    # Snapshot endpoints return the current state in one request with no query window,
    # so they sync as a full refresh keyed on these columns.
    snapshot_primary_keys: tuple[str, ...] | None = None


KUBECOST_ENDPOINTS: dict[str, KubecostEndpointConfig] = {
    "allocation_by_namespace": KubecostEndpointConfig(
        name="allocation_by_namespace",
        path="/model/allocation",
        params={"aggregate": "namespace"},
    ),
    "allocation_by_controller": KubecostEndpointConfig(
        name="allocation_by_controller",
        path="/model/allocation",
        params={"aggregate": "controller"},
    ),
    "allocation_by_pod": KubecostEndpointConfig(
        name="allocation_by_pod",
        path="/model/allocation",
        params={"aggregate": "pod"},
    ),
    "allocation_by_cluster": KubecostEndpointConfig(
        name="allocation_by_cluster",
        path="/model/allocation",
        params={"aggregate": "cluster"},
    ),
    "allocation_by_node": KubecostEndpointConfig(
        name="allocation_by_node",
        path="/model/allocation",
        params={"aggregate": "node"},
    ),
    "allocation_by_service": KubecostEndpointConfig(
        name="allocation_by_service",
        path="/model/allocation",
        params={"aggregate": "service"},
    ),
    "assets": KubecostEndpointConfig(
        name="assets",
        path="/model/assets",
    ),
    # Unaggregated, so each row is a single billing line item at full granularity.
    "cloud_costs": KubecostEndpointConfig(
        name="cloud_costs",
        path="/model/cloudCost",
        result_set_key="cloudCosts",
    ),
    "external_costs": KubecostEndpointConfig(
        name="external_costs",
        path="/model/customCost/timeseries",
        # Aggregating by every dimension keeps each line item distinct and gives it a
        # unique `aggregate` value within its window.
        params={
            "aggregate": "zone,accountName,chargeCategory,description,resourceName,"
            "resourceType,providerId,usageUnit,domain,costSource"
        },
        timeseries_items_key="customCosts",
    ),
    "request_sizing_recommendations": KubecostEndpointConfig(
        name="request_sizing_recommendations",
        path="/model/savings/requestSizingV2",
        # Kubecost recommends more than 2 days of usage for accurate sampling.
        params={"window": "7d"},
        snapshot_primary_keys=("clusterID", "namespace", "controllerKind", "controllerName", "containerName"),
    ),
    # Enterprise-only and disabled by default. It holds at most the 1000 most recent events
    # of the local cluster, and they do not survive a Kubecost restart.
    "audit_events": KubecostEndpointConfig(
        name="audit_events",
        path="/model/audit/events",
        snapshot_primary_keys=("key",),
    ),
}

ENDPOINTS = tuple(KUBECOST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(_WINDOW_INCREMENTAL_FIELDS)
    for name, config in KUBECOST_ENDPOINTS.items()
    if config.snapshot_primary_keys is None
}
