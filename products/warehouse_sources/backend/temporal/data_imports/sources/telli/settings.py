from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.telli.com"
PAGE_SIZE = 100


@frozen
class TelliEndpoint:
    endpoint: Endpoint
    primary_key: str = "id"
    partition_key: str = "createdAt"
    sort_mode: SortMode | None = None


ENDPOINTS: dict[str, TelliEndpoint] = {
    "calls": TelliEndpoint(
        endpoint={
            "path": "/v1/list-calls",
            "data_selector": "calls",
            "params": {"limit": PAGE_SIZE},
            "paginator": {"type": "cursor", "cursor_path": "next_cursor", "cursor_param": "cursor"},
        },
        primary_key="call_id",
        partition_key="triggered_at_iso",
        sort_mode="desc",
    ),
    "contacts": TelliEndpoint(
        endpoint={
            "path": "/v2/contacts",
            "data_selector": "data",
            "params": {"limit": PAGE_SIZE},
            "paginator": {"type": "cursor", "cursor_path": "pageInfo.nextCursor", "cursor_param": "cursor"},
        },
    ),
    "agents": TelliEndpoint(
        endpoint={
            "path": "/v2/agents",
            "data_selector": "data",
            "params": {"limit": PAGE_SIZE},
            "paginator": {"type": "cursor", "cursor_path": "pageInfo.nextCursor", "cursor_param": "cursor"},
        },
    ),
    "contact_properties": TelliEndpoint(
        endpoint={"path": "/v2/properties/contacts", "data_selector": "data", "paginator": "single_page"},
        primary_key="key",
    ),
    "phone_numbers": TelliEndpoint(
        endpoint={"path": "/v1/phone-numbers", "data_selector": "data", "paginator": "single_page"},
    ),
}

# None of the list endpoints exposes a server-side timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
