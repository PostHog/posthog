from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every Zoho CRM record carries these system fields. `Modified_Time` is what the
# `If-Modified-Since` header filters on server-side; `Created_Time` never changes, so it is
# the partition key.
MODIFIED_TIME_FIELD = "Modified_Time"
CREATED_TIME_FIELD = "Created_Time"


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

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.incremental:
            return []
        return [incremental_field(MODIFIED_TIME_FIELD, IncrementalFieldType.DateTime)]


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
    "Vendors": _module("Vendors"),
    # Inventory and support modules — edition/setup dependent.
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
}

ENDPOINTS = tuple(ZOHO_CRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ZOHO_CRM_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in ZOHO_CRM_ENDPOINTS.items()}
