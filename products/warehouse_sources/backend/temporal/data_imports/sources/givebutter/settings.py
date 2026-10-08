from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import PaginatorConfig
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.givebutter.com/v1/"
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)


@frozen
class GivebutterEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    parent: str | None = None
    data_selector: str | None = "data"
    paginator: PaginatorConfig | None = None
    page_size: int | None = PAGE_SIZE


ENDPOINTS: dict[str, GivebutterEndpoint] = {
    "campaigns": GivebutterEndpoint(path="campaigns"),
    "campaign_members": GivebutterEndpoint(
        path="campaigns/{parent_id}/members", parent="campaigns", primary_keys=("_campaigns_id", "id")
    ),
    "campaign_teams": GivebutterEndpoint(
        path="campaigns/{parent_id}/teams", parent="campaigns", primary_keys=("_campaigns_id", "id")
    ),
    "campaign_tickets": GivebutterEndpoint(
        path="campaigns/{parent_id}/items/tickets",
        parent="campaigns",
        primary_keys=("_campaigns_id", "id"),
        partition_key=None,
    ),
    "campaign_discount_codes": GivebutterEndpoint(
        path="campaigns/{parent_id}/discount-codes", parent="campaigns", primary_keys=("_campaigns_id", "id")
    ),
    "contacts": GivebutterEndpoint(path="contacts"),
    "contact_activities": GivebutterEndpoint(
        path="contacts/{parent_id}/activities", parent="contacts", primary_keys=("_contacts_id", "id")
    ),
    "funds": GivebutterEndpoint(path="funds"),
    "households": GivebutterEndpoint(
        path="households", data_selector=None, paginator=PageNumberPaginator(base_page=1), page_size=None
    ),
    "payouts": GivebutterEndpoint(path="payouts"),
    "plans": GivebutterEndpoint(path="plans"),
    "pledges": GivebutterEndpoint(path="pledges"),
    "tickets": GivebutterEndpoint(path="tickets"),
    "transactions": GivebutterEndpoint(path="transactions"),
}

# Timestamp filters in the public spec need a live-account filtering check before incremental sync is enabled.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
