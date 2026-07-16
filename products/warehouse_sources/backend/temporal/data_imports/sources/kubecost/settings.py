from dataclasses import dataclass, field

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


@dataclass
class KubecostEndpointConfig:
    name: str
    path: str
    # Extra query params sent on every request (e.g. the Allocation API's `aggregate`).
    params: dict[str, str] = field(default_factory=dict)


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
    "assets": KubecostEndpointConfig(
        name="assets",
        path="/model/assets",
    ),
}

ENDPOINTS = tuple(KUBECOST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(_WINDOW_INCREMENTAL_FIELDS) for name in KUBECOST_ENDPOINTS
}
