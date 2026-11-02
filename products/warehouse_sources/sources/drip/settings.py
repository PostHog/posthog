from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

DEFAULT_PAGE_SIZE = 100

# Campaign membership is only listable one status at a time, so a full membership table sweeps all
# three and tags each row with the status it came back under.
CAMPAIGN_SUBSCRIBER_STATUSES = ("active", "unsubscribed", "removed")
CAMPAIGN_SUBSCRIBER_STATUS_FIELD = "campaign_subscription_status"


@dataclass(frozen=True)
class DripEndpointConfig:
    name: str
    path: str
    # Key wrapping the list in the JSON response, e.g. {"subscribers": [...]}.
    data_key: str
    primary_keys: list[str]
    # Page size to request. None means the endpoint is not paginated (returns the full list in one response).
    per_page: Optional[int] = None
    # Explicit sort/direction for stable pagination. Only set where the endpoint documents a sort enum.
    sort: Optional[str] = None
    direction: Optional[str] = None
    # Stable datetime field to partition on. Never use updated_at (it changes and rewrites partitions).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Set when the endpoint returns a bare list of strings rather than objects; each value is wrapped
    # into a row under this column name.
    scalar_row_key: Optional[str] = None
    # Set when the endpoint is scoped to one parent resource and has to be fanned out over it.
    fanout: Optional[DependentEndpointConfig] = None

    # Both read by the shared fan-out helper. Every endpoint taking part in a fan-out sets
    # per_page, and no Drip endpoint has a usable cursor field.
    @property
    def page_size(self) -> int:
        return self.per_page if self.per_page is not None else DEFAULT_PAGE_SIZE

    @property
    def default_incremental_field(self) -> Optional[str]:
        return None


# Top-level, account-scoped endpoints (all require account_id as a path segment). We ship full refresh
# for every endpoint: Drip's only documented server-side timestamp filter is `subscribed_after` on
# subscribers, which filters on subscription (creation) date and so would silently miss updates to
# existing subscribers — not a safe incremental cursor. See PR notes.
DRIP_ENDPOINTS: dict[str, DripEndpointConfig] = {
    "subscribers": DripEndpointConfig(
        name="subscribers",
        path="/subscribers",
        data_key="subscribers",
        primary_keys=["id"],
        per_page=1000,  # documented max for this endpoint
        partition_key="created_at",
    ),
    "campaigns": DripEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_key="campaigns",
        primary_keys=["id"],
        per_page=100,
        sort="created_at",
        direction="asc",
    ),
    # Fanned out over campaigns: the rows are subscriber objects, so the campaign they belong to is
    # copied down from the parent and the primary key pairs the two.
    "campaign_subscribers": DripEndpointConfig(
        name="campaign_subscribers",
        path="/campaigns/{campaign_id}/subscribers",
        data_key="subscribers",
        primary_keys=["campaign_id", "id"],
        per_page=1000,  # documented max for this endpoint
        direction="asc",
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="campaigns",
            resolve_param="campaign_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "campaign_id"},
        ),
    ),
    "broadcasts": DripEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        data_key="broadcasts",
        primary_keys=["id"],
        per_page=100,
        sort="created_at",
        direction="asc",
    ),
    "workflows": DripEndpointConfig(
        name="workflows",
        path="/workflows",
        data_key="workflows",
        primary_keys=["id"],
        per_page=100,
    ),
    "forms": DripEndpointConfig(
        name="forms",
        path="/forms",
        data_key="forms",
        primary_keys=["id"],
    ),
    "goals": DripEndpointConfig(
        name="goals",
        path="/goals",
        data_key="goals",
        primary_keys=["id"],
    ),
    "tags": DripEndpointConfig(
        name="tags",
        path="/tags",
        data_key="tags",
        primary_keys=["tag"],
        scalar_row_key="tag",
    ),
    "custom_field_identifiers": DripEndpointConfig(
        name="custom_field_identifiers",
        path="/custom_field_identifiers",
        data_key="custom_field_identifiers",
        primary_keys=["identifier"],
        scalar_row_key="identifier",
    ),
}

ENDPOINTS = tuple(DRIP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DRIP_ENDPOINTS.items()
}
