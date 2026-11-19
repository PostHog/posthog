from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, incremental_field

# Every Zoho CRM record carries these system fields. `Modified_Time` is what the
# `If-Modified-Since` header filters on server-side; `Created_Time` never changes, so it is
# the partition key.
MODIFIED_TIME_FIELD = "Modified_Time"
CREATED_TIME_FIELD = "Created_Time"
# Timeline entries record when each change happened in `audited_time`; it never changes.
AUDITED_TIME_FIELD = "audited_time"

TERRITORIES_ENDPOINT = "Territories"
PIPELINES_ENDPOINT = "Pipelines"
DEAL_TIMELINE_ENDPOINT = "Deal_Timeline"
DEALS_MODULE = "Deals"
# Zoho lists pipelines per Deals layout, so each pipeline row carries its layout ID.
PIPELINE_LAYOUT_ID_FIELD = "layout_id"
# Timeline entries do not carry the record they belong to, so the timeline table adds it.
TIMELINE_DEAL_ID_FIELD = "deal_id"

# Module kinds that hold an org's own records and are readable through Get Records.
CUSTOM_MODULE_GENERATED_TYPES = frozenset({"custom", "linking"})
# Discovered modules get their own namespace, so an org's module named like a static table does
# not clash with it, and an unknown schema name fails before any request.
CUSTOM_MODULE_SCHEMA_PREFIX = "Custom_"


@dataclass(frozen=True)
class ZohoCRMEndpointConfig:
    name: str
    # Module API name for record modules (`/crm/{version}/{path}`), or the fixed path segment
    # for Zoho's own non-module endpoints.
    path: str
    # Record modules go through Get Records: their readable fields come from the fields
    # metadata API and they honour `If-Modified-Since`. Non-module endpoints (users) have a
    # different envelope, no field metadata, and no documented modified-since filter.
    is_module: bool = True
    # Key the records live under in the response body.
    data_key: str = "data"
    incremental: bool = True
    partition_key: Optional[str] = CREATED_TIME_FIELD
    # Modules that only exist on some Zoho CRM editions start unticked so a first sync doesn't
    # fail with INVALID_MODULE on an org that never enabled them.
    should_sync_default: bool = True
    # Extra query params Zoho requires on this endpoint.
    extra_params: Optional[dict[str, str]] = None
    incremental_field_name: str = MODIFIED_TIME_FIELD
    primary_keys: tuple[str, ...] = ("id",)
    sort_mode: Optional[Literal["asc", "desc"]] = "asc"

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.incremental:
            return []
        return [incremental_field(self.incremental_field_name, IncrementalFieldType.DateTime)]


def _module(name: str, should_sync_default: bool = True) -> ZohoCRMEndpointConfig:
    return ZohoCRMEndpointConfig(name=name, path=name, should_sync_default=should_sync_default)


ZOHO_CRM_ENDPOINTS: dict[str, ZohoCRMEndpointConfig] = {
    # Core CRM modules — present on every edition.
    "Leads": _module("Leads"),
    "Contacts": _module("Contacts"),
    "Accounts": _module("Accounts"),
    "Deals": _module("Deals"),
    "Campaigns": _module("Campaigns"),
    "Tasks": _module("Tasks"),
    "Events": _module("Events"),
    "Calls": _module("Calls"),
    "Notes": _module("Notes"),
    "Products": _module("Products"),
    # Inventory and support modules — edition/setup dependent.
    "Vendors": _module("Vendors", should_sync_default=False),
    "Price_Books": _module("Price_Books", should_sync_default=False),
    "Quotes": _module("Quotes", should_sync_default=False),
    "Sales_Orders": _module("Sales_Orders", should_sync_default=False),
    "Purchase_Orders": _module("Purchase_Orders", should_sync_default=False),
    "Invoices": _module("Invoices", should_sync_default=False),
    "Cases": _module("Cases", should_sync_default=False),
    "Solutions": _module("Solutions", should_sync_default=False),
    # Org users are served by a dedicated endpoint, not the Get Records API.
    "Users": ZohoCRMEndpointConfig(
        name="Users",
        path="users",
        is_module=False,
        data_key="users",
        incremental=False,
        # The users endpoint names its system fields in lower case, unlike record modules.
        partition_key="created_time",
        extra_params={"type": "AllUsers"},
    ),
    # Territory management and pipelines are edition features, and each needs a settings scope
    # that the original setup did not ask for, so both start unticked.
    TERRITORIES_ENDPOINT: ZohoCRMEndpointConfig(
        name=TERRITORIES_ENDPOINT,
        path="settings/territories",
        is_module=False,
        data_key="territories",
        incremental=False,
        partition_key=None,
        should_sync_default=False,
    ),
    PIPELINES_ENDPOINT: ZohoCRMEndpointConfig(
        name=PIPELINES_ENDPOINT,
        path="settings/pipeline",
        is_module=False,
        data_key="pipeline",
        incremental=False,
        partition_key=None,
        should_sync_default=False,
        primary_keys=(PIPELINE_LAYOUT_ID_FIELD, "id"),
    ),
    # One request per deal, so it is opt-in. Rows arrive per deal, not in one ordered series.
    DEAL_TIMELINE_ENDPOINT: ZohoCRMEndpointConfig(
        name=DEAL_TIMELINE_ENDPOINT,
        path="__timeline",
        is_module=False,
        data_key="__timeline",
        incremental_field_name=AUDITED_TIME_FIELD,
        partition_key=AUDITED_TIME_FIELD,
        should_sync_default=False,
        primary_keys=(TIMELINE_DEAL_ID_FIELD, "id"),
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(ZOHO_CRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ZOHO_CRM_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in ZOHO_CRM_ENDPOINTS.items()}


def custom_module_config(api_name: str) -> ZohoCRMEndpointConfig:
    """Config for a custom or linking module found by discovery. These start unticked."""
    return ZohoCRMEndpointConfig(
        name=f"{CUSTOM_MODULE_SCHEMA_PREFIX}{api_name}", path=api_name, should_sync_default=False
    )


def endpoint_config(name: str) -> ZohoCRMEndpointConfig:
    """The static config for `name`, else the discovered custom or linking module it names."""
    if name in ZOHO_CRM_ENDPOINTS:
        return ZOHO_CRM_ENDPOINTS[name]
    api_name = name.removeprefix(CUSTOM_MODULE_SCHEMA_PREFIX)
    if api_name and api_name != name:
        return custom_module_config(api_name)
    raise ValueError(f"Unknown Zoho CRM schema: {name}")
