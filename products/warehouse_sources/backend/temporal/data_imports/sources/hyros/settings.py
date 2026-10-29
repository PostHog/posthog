from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Hyros caps `pageSize` at 250 on every cursor-paginated list endpoint.
PAGE_SIZE = 250


def _incremental_field(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class HyrosEndpointConfig:
    name: str
    path: str  # under https://api.hyros.com/v1
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Query parameter Hyros expects for the incremental start-date filter (e.g. "fromDate" or
    # "updatedFromDate"). None when the endpoint has no server-side date filter.
    incremental_query_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. None when there's no reliable created-date column.
    partition_key: Optional[str] = None
    # Fixed query parameters sent on every request, e.g. a required enum filter.
    params: dict[str, Any] = field(default_factory=dict)
    # Hyros doesn't document the order `pageId` cursoring returns rows in. Ascending is the
    # conservative default the framework and every other cursor-paginated source here assume;
    # flag it explicitly since it's unverified rather than confirmed against the live API.
    sort_mode: Optional[SortMode] = "asc"

    @property
    def incremental_field_name(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


HYROS_ENDPOINTS: dict[str, HyrosEndpointConfig] = {
    "Leads": HyrosEndpointConfig(
        name="Leads",
        path="/api/v1.0/leads",
        primary_keys=["id"],
        # `updatedFromDate` filters on `lastUpdatedDate`, so it also catches tag/stage changes
        # on existing leads that `fromDate` (join date only) would miss.
        incremental_query_param="updatedFromDate",
        incremental_fields=_incremental_field("lastUpdatedDate"),
        partition_key="creationDate",
    ),
    "Sales": HyrosEndpointConfig(
        name="Sales",
        path="/api/v1.0/sales",
        primary_keys=["id"],
        incremental_query_param="fromDate",
        incremental_fields=_incremental_field("creationDate"),
        partition_key="creationDate",
    ),
    "Calls": HyrosEndpointConfig(
        name="Calls",
        path="/api/v1.0/calls",
        primary_keys=["id"],
        incremental_query_param="fromDate",
        incremental_fields=_incremental_field("creationDate"),
        partition_key="creationDate",
    ),
    "Subscriptions": HyrosEndpointConfig(
        name="Subscriptions",
        path="/api/v1.0/subscriptions",
        primary_keys=["id"],
        # The API docs don't name which field `fromDate`/`toDate` filters on subscriptions.
        # `startDate` is the closest analogue to the creation-date filter documented on
        # leads/sales/calls, so it's used for both the incremental cursor and partitioning.
        incremental_query_param="fromDate",
        incremental_fields=_incremental_field("startDate"),
        partition_key="startDate",
    ),
    "Sources": HyrosEndpointConfig(
        name="Sources",
        path="/api/v1.0/sources",
        # `tag` (e.g. "@facebook-adset") is the identifier the API itself uses to address a
        # source (see `PUT /sources/{tag}`); the object has no `id` field.
        primary_keys=["tag"],
    ),
    "Tags": HyrosEndpointConfig(
        name="Tags",
        # `GET /tags` is deprecated in favor of this endpoint, which also returns lead counts.
        path="/api/v1.0/tags/count",
        primary_keys=["name"],
    ),
    "Keywords": HyrosEndpointConfig(
        name="Keywords",
        path="/api/v1.0/keywords",
        primary_keys=["id"],
    ),
    "Stages": HyrosEndpointConfig(
        name="Stages",
        path="/api/v1.0/stages",
        primary_keys=["name"],
    ),
    "AdAccounts": HyrosEndpointConfig(
        name="AdAccounts",
        path="/api/v1.0/ad-accounts",
        primary_keys=["id"],
    ),
    "Ads": HyrosEndpointConfig(
        name="Ads",
        path="/api/v1.0/ads",
        # Ad rows carry no `id`; the platform ad id lives on the nested `adSource` and is lifted to
        # the row root in transport. Ad ids are only unique within a platform.
        primary_keys=["platform", "adSourceId"],
    ),
    "Products": HyrosEndpointConfig(
        name="Products",
        path="/api/v1.0/products",
        primary_keys=["id"],
    ),
    "Carts": HyrosEndpointConfig(
        name="Carts",
        path="/api/v1.0/carts",
        primary_keys=["id"],
        # Full refresh only: `fromDate` filters on the creation date, but a cart gains its `orderId`
        # when it is purchased later.
        partition_key="creationDate",
    ),
    "CustomCosts": HyrosEndpointConfig(
        name="CustomCosts",
        path="/api/v1.0/custom-costs",
        primary_keys=["id"],
        # `fromDate` matches costs whose active range overlaps the window, not a change date, so it
        # can't serve as an incremental cursor.
    ),
    **{
        name: HyrosEndpointConfig(
            name=name,
            path="/api/v1.0/conversion-paths",
            primary_keys=["id"],
            # `fromDate` filters on the sale date, which is what `creationDate` holds. The path only
            # covers touches up to that date, so a synced row doesn't change later.
            incremental_query_param="fromDate",
            incremental_fields=_incremental_field("creationDate"),
            partition_key="creationDate",
            params={"conversionType": conversion_type},
            # The API doesn't document the order conversions are paged in.
            sort_mode=None,
        )
        for name, conversion_type in (
            ("SaleConversionPaths", "SALE"),
            ("CallConversionPaths", "CALL"),
        )
    },
    "LeadConversionPaths": HyrosEndpointConfig(
        name="LeadConversionPaths",
        path="/api/v1.0/conversion-paths",
        primary_keys=["id"],
        # Full refresh only: `fromDate` filters on the join date, but `path` is the lead's full touch
        # list and keeps growing after it joins.
        partition_key="creationDate",
        params={"conversionType": "LEAD"},
    ),
}

ENDPOINTS = tuple(HYROS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HYROS_ENDPOINTS.items()
}
