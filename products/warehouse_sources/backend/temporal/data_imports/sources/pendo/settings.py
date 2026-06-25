from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Pendo hosts each subscription in a region-specific data center and the integration key is
# region-scoped, so the base URL has to match where the subscription lives.
# https://support.pendo.io/hc/en-us/articles/22832528657179-Global-data-hosting
PENDO_REGION_BASE_URLS: dict[str, str] = {
    "us": "https://app.pendo.io",
    "us1": "https://us1.app.pendo.io",
    "eu": "https://app.eu.pendo.io",
    "jp": "https://app.jpn.pendo.io",
    "au": "https://app.au.pendo.io",
}

DEFAULT_REGION = "us"


@dataclass
class PendoEndpointConfig:
    name: str
    primary_keys: list[str]
    # GET list endpoints (feature/page/guide) set `path`; aggregation endpoints
    # (visitors/accounts) set `aggregation_source` and POST to /api/v1/aggregation.
    path: Optional[str] = None
    aggregation_source: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)

    @property
    def is_aggregation(self) -> bool:
        return self.aggregation_source is not None


# All endpoints are full refresh: Pendo's list endpoints expose no server-side timestamp
# filter, and the aggregation endpoint's time filters only apply to event sources, not the
# visitor/account metadata we pull here. A client-side cursor would still read every row each
# run, so it would not be a genuine incremental sync.
PENDO_ENDPOINTS: dict[str, PendoEndpointConfig] = {
    "features": PendoEndpointConfig(name="features", path="/api/v1/feature", primary_keys=["id"]),
    "pages": PendoEndpointConfig(name="pages", path="/api/v1/page", primary_keys=["id"]),
    "guides": PendoEndpointConfig(name="guides", path="/api/v1/guide", primary_keys=["id"]),
    "visitors": PendoEndpointConfig(name="visitors", aggregation_source="visitors", primary_keys=["visitorId"]),
    "accounts": PendoEndpointConfig(name="accounts", aggregation_source="accounts", primary_keys=["accountId"]),
}

ENDPOINTS = tuple(PENDO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PENDO_ENDPOINTS.items()
}
