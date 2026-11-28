from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, frozen

# Zoho Desk's list endpoints have no modified-time filter. Their only time-based option is a
# `createdTime` sort, and the modified-time filter exists only on the search endpoints, which stop
# at 5000 results. Every table is therefore a full refresh.
CREATED_TIME_FIELD = "createdTime"


@frozen
class ZohoDeskEndpointConfig:
    name: str
    path: str
    data_selector: str = "data"
    page_size: int = 100
    first_index: int = 1
    # Set for an endpoint that accepts `from=0` but does not say whether it counts from 0 or from 1.
    # Paging from 0 loses no record under either reading. If the endpoint counts from 1, the first
    # record of each later page repeats the last record of the page before it, so repeats are dropped.
    drop_repeated_ids: bool = False
    sort_by: Optional[str] = CREATED_TIME_FIELD
    partition_key: Optional[str] = CREATED_TIME_FIELD
    extra_params: Optional[dict[str, str]] = None
    should_sync_default: bool = True


ZOHO_DESK_ENDPOINTS: dict[str, ZohoDeskEndpointConfig] = {
    config.name: config
    for config in (
        ZohoDeskEndpointConfig(name="tickets", path="/tickets"),
        ZohoDeskEndpointConfig(name="contacts", path="/contacts"),
        ZohoDeskEndpointConfig(name="accounts", path="/accounts"),
        ZohoDeskEndpointConfig(
            name="agents",
            path="/agents",
            page_size=200,
            first_index=0,
            drop_repeated_ids=True,
            sort_by=None,
            partition_key=None,
        ),
        ZohoDeskEndpointConfig(
            name="departments",
            path="/departments",
            page_size=200,
            first_index=0,
            drop_repeated_ids=True,
            sort_by=None,
            partition_key=None,
        ),
        ZohoDeskEndpointConfig(
            name="teams",
            path="/teams",
            data_selector="teams",
            page_size=200,
            first_index=0,
            sort_by=None,
            partition_key=None,
        ),
        ZohoDeskEndpointConfig(
            name="products",
            path="/products",
            partition_key=None,
            # Zoho documents `0` as the value that lists products from every accessible department.
            extra_params={"departmentId": "0"},
        ),
        ZohoDeskEndpointConfig(name="tasks", path="/tasks"),
        ZohoDeskEndpointConfig(name="calls", path="/calls", should_sync_default=False),
        ZohoDeskEndpointConfig(name="events", path="/events", should_sync_default=False),
        ZohoDeskEndpointConfig(name="contracts", path="/contracts", partition_key=None, should_sync_default=False),
    )
}

ENDPOINTS = tuple(ZOHO_DESK_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ZOHO_DESK_ENDPOINTS}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    name: config.should_sync_default for name, config in ZOHO_DESK_ENDPOINTS.items()
}
