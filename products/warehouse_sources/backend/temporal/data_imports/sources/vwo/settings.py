from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

API_ORIGIN = "https://app.wingify.com/api"
PAGE_SIZE = 25


@frozen
class VWOEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    paginated: bool = False
    singleton: bool = False
    partition_field: str | None = None
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


CAMPAIGN_FANOUT = DependentEndpointConfig(
    parent_name="campaigns",
    resolve_param="campaign_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "campaign_id"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# VWO documents no timestamp filter. Offset ordering and envelopes need verification with a live account.
ENDPOINTS: dict[str, VWOEndpoint] = {
    "accounts": VWOEndpoint(name="accounts", path="accounts/{account_id}", singleton=True, partition_field="createdOn"),
    "campaigns": VWOEndpoint(
        name="campaigns", path="accounts/{account_id}/campaigns", paginated=True, partition_field="createdOn"
    ),
    "campaign_sections": VWOEndpoint(
        name="campaign_sections",
        path="accounts/{account_id}/campaigns/{campaign_id}/sections",
        primary_keys=("campaign_id", "id"),
        fanout=CAMPAIGN_FANOUT,
    ),
    "feature_flags": VWOEndpoint(name="feature_flags", path="accounts/{account_id}/features", paginated=True),
    "goals": VWOEndpoint(
        name="goals",
        path="accounts/{account_id}/campaigns/{campaign_id}/goals",
        primary_keys=("campaign_id", "id"),
        fanout=CAMPAIGN_FANOUT,
    ),
    "metric_reports": VWOEndpoint(
        name="metric_reports",
        path="accounts/{account_id}/insights-metrics",
        paginated=True,
        partition_field="createdOn",
    ),
    "variations": VWOEndpoint(
        name="variations",
        path="accounts/{account_id}/campaigns/{campaign_id}/variations",
        primary_keys=("campaign_id", "sectionId", "id"),
        fanout=CAMPAIGN_FANOUT,
    ),
    "websites": VWOEndpoint(name="websites", path="accounts/{account_id}/websites", partition_field="createdAt"),
}
INCREMENTAL_FIELDS = {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}
