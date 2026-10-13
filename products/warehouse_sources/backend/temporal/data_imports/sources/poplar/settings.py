from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.heypoplar.com/v1"
AUTH_ERROR = (
    "Poplar rejected the access token. Check that it is a production token and that it has not been revoked. "
    "Test tokens can only send mailings, so they cannot read data."
)


@frozen
class PoplarEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    data_selector: str | None = None
    # 0 means the endpoint returns the whole collection in one response.
    page_size: int = 0
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


# Creative and mailing ids are only documented under their campaign, so the campaign id is part of both keys.
CAMPAIGN_FANOUT = DependentEndpointConfig(
    parent_name="campaigns",
    resolve_param="campaign_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "campaign_id"},
)

ENDPOINTS = {
    "campaigns": PoplarEndpoint(name="campaigns", path="campaigns", primary_keys=("id",)),
    "campaign_creatives": PoplarEndpoint(
        name="campaign_creatives",
        path="campaign/{campaign_id}/creatives",
        primary_keys=("campaign_id", "id"),
        fanout=CAMPAIGN_FANOUT,
    ),
    "campaign_mailings": PoplarEndpoint(
        name="campaign_mailings",
        path="campaign/{campaign_id}/mailings",
        primary_keys=("campaign_id", "id"),
        page_size=100,
        partition_key="created_at",
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        fanout=CAMPAIGN_FANOUT,
    ),
    # No date range is sent, so each row is the lifetime total for one campaign. The API does not say
    # whether a date range narrows the totals or only the list of campaigns, so a per-day table could
    # store lifetime totals under every day.
    "campaign_stats": PoplarEndpoint(
        name="campaign_stats",
        path="stats/campaigns",
        primary_keys=("campaign_id",),
        data_selector="campaigns",
        page_size=30,
    ),
    "audiences": PoplarEndpoint(name="audiences", path="audiences", primary_keys=("id",)),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}
