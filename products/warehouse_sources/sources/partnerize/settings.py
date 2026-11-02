from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class PartnerizeEndpointConfig:
    name: str
    # Path relative to the API base. `{publisher_id}` is substituted with the configured partner ID.
    path: str
    # Key the row list is nested under in the response body (e.g. {"conversions": [...]}).
    data_key: str
    # Partnerize wraps every list item in a single-key object (e.g. {"campaign": {...}},
    # {"conversion_data": {...}}); this is that inner key. None when rows are flat.
    item_key: Optional[str]
    primary_keys: list[str]
    # "report" endpoints take a required start_date/end_date window and paginate by offset;
    # "list" endpoints return everything, following hypermedia.pagination.next_page when present.
    kind: Literal["report", "list"] = "list"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Extra query params keyed by the user's chosen incremental field. Partnerize's report
    # endpoints filter on the conversion time by default; passing date_type=last_updated makes
    # the start_date/end_date window apply to last_modified instead.
    incremental_field_params: dict[str, dict[str, str]] = field(default_factory=dict)
    # Nested list on each unwrapped item to emit as its own rows, one per element. Each row also
    # carries `explode_parent_fields` copied from the item it was nested under.
    explode_key: Optional[str] = None
    explode_parent_fields: list[str] = field(default_factory=list)
    # Set for per-campaign endpoints, which fan out over the parent endpoint's rows.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out helper only. No Partnerize endpoint takes a page-size param, so
    # the helper is called with page_size_param=None and never sends it.
    default_incremental_field: Optional[str] = None
    page_size: int = 300


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Partnerize Partner API endpoints (https://api-docs.partnerize.com/partner/). The conversions,
# conversion items, and clicks reports accept a server-side start_date/end_date window, so they support incremental sync;
# campaigns and the reference catalogs expose no timestamp filter and are full refresh only.
PARTNERIZE_ENDPOINTS: dict[str, PartnerizeEndpointConfig] = {
    "campaigns": PartnerizeEndpointConfig(
        name="campaigns",
        # `/a` restricts the list to campaigns the partner is approved on.
        path="/user/publisher/{publisher_id}/campaign/a",
        data_key="campaigns",
        item_key="campaign",
        primary_keys=["campaign_id"],
    ),
    "conversions": PartnerizeEndpointConfig(
        name="conversions",
        path="/reporting/report_publisher/publisher/{publisher_id}/conversion.json",
        data_key="conversions",
        item_key="conversion_data",
        primary_keys=["conversion_id"],
        kind="report",
        partition_key="conversion_time",
        incremental_fields=[_datetime_field("conversion_time"), _datetime_field("last_modified")],
        # date_type=last_updated re-windows the report on last_modified, so status changes
        # (pending -> approved/rejected) on old conversions are picked up.
        incremental_field_params={"last_modified": {"date_type": "last_updated"}},
    ),
    "conversion_items": PartnerizeEndpointConfig(
        name="conversion_items",
        # The JSON conversion report nests each conversion's line items, so this is the same data as
        # the conversion_item.csv export, paged and windowed like the conversions table.
        path="/reporting/report_publisher/publisher/{publisher_id}/conversion.json",
        data_key="conversions",
        item_key="conversion_data",
        explode_key="conversion_items",
        explode_parent_fields=[
            "conversion_id",
            "campaign_id",
            "publisher_id",
            "conversion_time",
            "last_modified",
            "currency",
        ],
        # The docs don't state that conversion_item_id is unique outside its conversion.
        primary_keys=["conversion_id", "conversion_item_id"],
        kind="report",
        partition_key="conversion_time",
        incremental_fields=[_datetime_field("conversion_time"), _datetime_field("last_modified")],
        incremental_field_params={"last_modified": {"date_type": "last_updated"}},
    ),
    "clicks": PartnerizeEndpointConfig(
        name="clicks",
        path="/reporting/report_publisher/publisher/{publisher_id}/click.json",
        data_key="clicks",
        item_key="click",
        # clickref is Partnerize's click reference; the docs don't state global uniqueness, so the
        # campaign is included to keep the key unique table-wide.
        primary_keys=["campaign_id", "clickref"],
        kind="report",
        partition_key="set_time",
        incremental_fields=[_datetime_field("set_time")],
    ),
    "advertisers": PartnerizeEndpointConfig(
        name="advertisers",
        # Brands with campaigns the partner can join, each with its campaigns and the partner's
        # status on them.
        path="/v2/publishers/{publisher_id}/discovery/advertisers",
        data_key="advertisers",
        item_key=None,
        primary_keys=["id"],
    ),
    "commissions": PartnerizeEndpointConfig(
        name="commissions",
        # Every active commission (default, campaign, voucher, promotional, and tier) for the partner
        # on one campaign. The per-type /default, /campaign, /voucher, /promotion, and /tier routes
        # return subsets of these rows.
        path="/v2/campaigns/{campaign_id}/publishers/{publisher_id}/commissions/active",
        data_key="active_commissions",
        item_key=None,
        # Commission ids are per campaign, and standard and tier commissions are separate objects.
        primary_keys=["campaign_id", "type", "id"],
        fanout=DependentEndpointConfig(
            parent_name="campaigns",
            resolve_param="campaign_id",
            resolve_field="campaign_id",
            include_from_parent=["campaign_id"],
            parent_field_renames={"campaign_id": "campaign_id"},
            # Partnerize answers 404 for an entity it can't find, so a campaign the partner leaves
            # between the two requests drops its rows instead of failing the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "countries": PartnerizeEndpointConfig(
        name="countries",
        path="/reference/country",
        data_key="countries",
        item_key="country",
        primary_keys=["ref_country_id"],
    ),
    "currencies": PartnerizeEndpointConfig(
        name="currencies",
        path="/reference/currency",
        data_key="currencies",
        item_key="currency",
        primary_keys=["currency_id"],
    ),
    "devices": PartnerizeEndpointConfig(
        name="devices",
        path="/reference/device",
        data_key="devices",
        item_key="device",
        primary_keys=["ref_device_id"],
    ),
    "timezones": PartnerizeEndpointConfig(
        name="timezones",
        path="/reference/timezone",
        data_key="timezones",
        item_key="timezone",
        primary_keys=["ref_timezone_id"],
    ),
    "traffic_sources": PartnerizeEndpointConfig(
        name="traffic_sources",
        path="/reference/traffic_source",
        data_key="traffic_sources",
        item_key="traffic_source",
        primary_keys=["ref_traffic_source_id"],
    ),
    "user_contexts": PartnerizeEndpointConfig(
        name="user_contexts",
        path="/reference/user_context",
        data_key="user_contexts",
        item_key="user_context",
        primary_keys=["ref_user_context_id"],
    ),
    "conversion_types": PartnerizeEndpointConfig(
        name="conversion_types",
        path="/reference/conversion_type",
        data_key="conversion_types",
        item_key="conversion_type",
        primary_keys=["conversion_type_id"],
    ),
    "conversion_metrics": PartnerizeEndpointConfig(
        name="conversion_metrics",
        path="/reference/conversion_metric",
        data_key="conversion_metrics",
        item_key="conversion_metric",
        primary_keys=["ref_conversion_metric_id"],
    ),
    "partnership_models": PartnerizeEndpointConfig(
        name="partnership_models",
        path="/reference/partnership_model",
        data_key="partnership_models",
        item_key="partnership_model",
        primary_keys=["ref_partnership_model_id"],
    ),
}

ENDPOINTS = tuple(PARTNERIZE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PARTNERIZE_ENDPOINTS.items() if config.incremental_fields
}
