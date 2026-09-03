from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# Nuntly caps every list endpoint at 30 rows per page (no larger tier is documented).
MAX_PAGE_SIZE = 30


@frozen
class NuntlyEndpointConfig:
    path: str
    table_name: str
    primary_keys: list[str]
    # `createdAt` is stable across every endpoint below; none expose an `updated_at` equivalent.
    partition_key: str = "createdAt"


ENDPOINTS: dict[str, NuntlyEndpointConfig] = {
    "Emails": NuntlyEndpointConfig(path="/emails", table_name="emails", primary_keys=["id"]),
    "Messages": NuntlyEndpointConfig(path="/messages", table_name="messages", primary_keys=["id"]),
    "Inboxes": NuntlyEndpointConfig(path="/inboxes", table_name="inboxes", primary_keys=["id"]),
    "Domains": NuntlyEndpointConfig(path="/domains", table_name="domains", primary_keys=["id"]),
    "Webhooks": NuntlyEndpointConfig(path="/webhooks", table_name="webhooks", primary_keys=["id"]),
}

# Nuntly documents no server-side timestamp filter on any list endpoint (no `since` /
# `updated_after` / date-range param), so every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
