from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Partnerize Partner API endpoints (https://api-docs.partnerize.com/partner/). The conversions and
# clicks reports accept a server-side start_date/end_date window, so they support incremental sync;
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
