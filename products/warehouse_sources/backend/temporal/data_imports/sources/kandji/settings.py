from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Kandji's List Devices endpoint caps `limit` at 300; the other list endpoints share the same cap.
DEVICES_PAGE_SIZE = 300

# Kandji exposes per-tenant, region-scoped base URLs. Both region and subdomain are user-supplied,
# and the API lives under the `/api/v1` prefix on that host.
US_API_HOST_TEMPLATE = "https://{subdomain}.api.kandji.io/api/v1"
EU_API_HOST_TEMPLATE = "https://{subdomain}.api.eu.kandji.io/api/v1"


@dataclass
class KandjiEndpointConfig:
    name: str
    path: str
    # jsonpath selector into the response body: "$" for a bare array, or the wrapper key
    # ("results", "apps", "library_items") for endpoints that nest their rows.
    data_selector: str
    primary_key: str | list[str]
    # Top-level list endpoints paginate with limit/offset. Per-device children return the full
    # list in one response, so they are fetched as a single page.
    paginated: bool = True
    # `total`-like count field in the response, used to terminate offset pagination. `None` when the
    # endpoint returns a bare array with no count (we then stop on the first empty/short page).
    total_path: str | None = None
    page_size: int = DEVICES_PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    # Kandji has no server-side updated-since filter on these endpoints, so every stream is
    # full-refresh; these stay empty but satisfy the fan-out helper's endpoint protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


KANDJI_ENDPOINTS: dict[str, KandjiEndpointConfig] = {
    "devices": KandjiEndpointConfig(
        name="devices",
        path="/devices",
        # List Devices returns a bare JSON array with no count/next, so we page until an empty response.
        data_selector="$",
        primary_key="device_id",
        total_path=None,
    ),
    "blueprints": KandjiEndpointConfig(
        name="blueprints",
        path="/blueprints",
        # Blueprints uses the wrapped `{count, next, previous, results}` shape.
        data_selector="results",
        primary_key="id",
        total_path="count",
    ),
    "device_details": KandjiEndpointConfig(
        name="device_details",
        path="/devices/{device_id}/details",
        # Details returns a single nested object per device; `$` selects that object.
        data_selector="$",
        primary_key="device_id",
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="devices",
            resolve_param="device_id",
            resolve_field="device_id",
            include_from_parent=["device_id"],
            parent_field_renames={"device_id": "device_id"},
        ),
    ),
    "device_apps": KandjiEndpointConfig(
        name="device_apps",
        path="/devices/{device_id}/apps",
        data_selector="apps",
        # App rows are unique per device; `bundle_id` identifies the app within a device. The parent
        # device id keeps the key unique across the table (this stream aggregates every device's apps).
        primary_key=["device_id", "bundle_id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="devices",
            resolve_param="device_id",
            resolve_field="device_id",
            include_from_parent=["device_id"],
            parent_field_renames={"device_id": "device_id"},
        ),
    ),
    "device_library_items": KandjiEndpointConfig(
        name="device_library_items",
        path="/devices/{device_id}/library-items",
        data_selector="library_items",
        # Library-item `id` is unique within a device; the parent device id keeps it unique table-wide.
        primary_key=["device_id", "id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="devices",
            resolve_param="device_id",
            resolve_field="device_id",
            include_from_parent=["device_id"],
            parent_field_renames={"device_id": "device_id"},
        ),
    ),
}

ENDPOINTS = tuple(KANDJI_ENDPOINTS)

# Kandji's documented list endpoints expose no reliable updated-since/created-since filter or stable
# cursor, so every stream is full-refresh only. No endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in KANDJI_ENDPOINTS}
