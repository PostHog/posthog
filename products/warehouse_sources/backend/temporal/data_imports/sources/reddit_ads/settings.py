from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class EndpointConfig:
    resource: EndpointResource
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1
    should_sync_default: bool = True


def _entity_endpoint(
    name: str,
    path: str,
    *,
    primary_key: list[str],
    partition_key: Optional[str] = None,
) -> EndpointConfig:
    """A plain account-scoped GET list endpoint.

    None of these accept a server-side timestamp filter (only `page.token` / `page.size` and a few
    value filters), so they stay full refresh — see the Reddit Ads v3 OpenAPI spec.
    """
    return EndpointConfig(
        resource={
            "name": name,
            "table_name": name,
            "primary_key": primary_key,
            "endpoint": {
                "path": path,
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
            },
            "table_format": "delta",
        },
        partition_keys=[partition_key] if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="week" if partition_key else None,
    )


# Metrics requested for every breakdown report table. Deliberately narrower than the entity-level
# report tables: reach and frequency only exist from June 2024 and the app-install family is
# objective-specific, so neither survives a per-dimension breakdown usefully.
_BREAKDOWN_REPORT_METRICS = [
    "CLICKS",
    "CONVERSION_PURCHASE_TOTAL_ITEMS",
    "CONVERSION_PURCHASE_TOTAL_VALUE",
    "CONVERSION_ROAS",
    "CPC",
    "CTR",
    "CURRENCY",
    "ECPM",
    "IMPRESSIONS",
    "KEY_CONVERSION_RATE",
    "KEY_CONVERSION_TOTAL_COUNT",
    "SPEND",
    "VIDEO_COMPLETION_RATE",
    "VIDEO_STARTED",
    "VIDEO_VIEW_RATE",
    "VIDEO_WATCHED_100_PERCENT",
    "VIDEO_WATCHED_25_PERCENT",
    "VIDEO_WATCHED_50_PERCENT",
    "VIDEO_WATCHED_75_PERCENT",
]


def _breakdown_report_endpoint(
    name: str,
    breakdown: str,
    column: str,
    *,
    breakdown_is_requestable_field: bool = True,
) -> EndpointConfig:
    """A campaign-grain report broken down by one extra dimension.

    Reddit returns breakdowns as extra dimensions on the same `POST /reports` call rather than from a
    separate endpoint, so each dimension is its own table with its own `breakdowns` array. Reddit caps
    a request at three breakdowns, which `CAMPAIGN_ID` + `DATE` + the dimension exactly fills.

    A few breakdowns (`OS_TYPE`, `LANGUAGE`, `METRO`, ...) are not members of the `fields` enum even
    though the response carries their column, so those are requested as a breakdown only.
    """
    fields = ["CAMPAIGN_ID", "DATE", *_BREAKDOWN_REPORT_METRICS]
    if breakdown_is_requestable_field:
        fields.append(breakdown)

    return EndpointConfig(
        resource={
            "name": name,
            "table_name": name,
            "primary_key": ["campaign_id", "date", column],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["CAMPAIGN_ID", "DATE", breakdown],
                        "fields": sorted(fields),
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        # One report request per dimension value per day is expensive and only some advertisers
        # break spend down this way, so these stay off unless the user picks them.
        should_sync_default=False,
    )


REDDIT_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        resource={
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/campaigns",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "ad_groups": EndpointConfig(
        resource={
            "name": "ad_groups",
            "table_name": "ad_groups",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/ad_groups",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "ads": EndpointConfig(
        resource={
            "name": "ads",
            "table_name": "ads",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/ads",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "campaign_report": EndpointConfig(
        resource={
            "name": "campaign_report",
            "table_name": "campaign_report",
            "primary_key": ["campaign_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["CAMPAIGN_ID", "DATE"],
                        "fields": [
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CAMPAIGN_ID",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "DATE",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "ad_group_report": EndpointConfig(
        resource={
            "name": "ad_group_report",
            "table_name": "ad_group_report",
            "primary_key": ["ad_group_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_GROUP_ID", "DATE"],
                        "fields": [
                            "AD_GROUP_ID",
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "ad_report": EndpointConfig(
        resource={
            "name": "ad_report",
            "table_name": "ad_report",
            "primary_key": ["ad_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_ID", "DATE"],
                        "fields": [
                            "AD_ID",
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "DATE",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
    ),
    "ad_account": _entity_endpoint(
        "ad_account",
        "/ad_accounts/{account_id}",
        primary_key=["id"],
    ),
    "custom_audiences": _entity_endpoint(
        "custom_audiences",
        "/ad_accounts/{account_id}/custom_audiences",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "saved_audiences": _entity_endpoint(
        "saved_audiences",
        "/ad_accounts/{account_id}/saved_audiences",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "pixels": _entity_endpoint(
        "pixels",
        "/ad_accounts/{account_id}/pixels",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "funding_instruments": _entity_endpoint(
        "funding_instruments",
        "/ad_accounts/{account_id}/funding_instruments",
        primary_key=["id"],
    ),
    "lead_gen_forms": _entity_endpoint(
        "lead_gen_forms",
        "/ad_accounts/{account_id}/lead_gen_forms",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "profiles": _entity_endpoint(
        "profiles",
        "/ad_accounts/{account_id}/profiles",
        primary_key=["id"],
    ),
    "structured_posts": EndpointConfig(
        resource={
            "name": "structured_posts",
            "table_name": "structured_posts",
            # Fanned out over every profile on the account, so the parent id is part of the key.
            "primary_key": ["profile_id", "id"],
            "endpoint": {
                "path": "/profiles/{profile_id}/structured_posts",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
            },
            "table_format": "delta",
        },
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
    ),
    "campaign_country_report": _breakdown_report_endpoint("campaign_country_report", "COUNTRY", "country"),
    "campaign_gender_report": _breakdown_report_endpoint("campaign_gender_report", "GENDER", "gender"),
    "campaign_placement_report": _breakdown_report_endpoint("campaign_placement_report", "PLACEMENT", "placement"),
    "campaign_community_report": _breakdown_report_endpoint("campaign_community_report", "COMMUNITY", "community"),
    "campaign_os_type_report": _breakdown_report_endpoint(
        "campaign_os_type_report",
        "OS_TYPE",
        "os_type",
        # `OS_TYPE` is a valid breakdown but is not a member of the report `fields` enum, so asking
        # for it as a field would be rejected. The response carries `os_type` from the breakdown.
        breakdown_is_requestable_field=False,
    ),
    "campaign_keyword_report": _breakdown_report_endpoint(
        "campaign_keyword_report",
        "KEYWORD",
        "keyword",
        # Requested as a breakdown only, because whether `KEYWORD` is a member of the report `fields`
        # enum has not been confirmed against the v3 spec. Sending a field Reddit does not accept
        # fails the whole report request, so this takes the conservative side of that unknown.
        breakdown_is_requestable_field=False,
    ),
}

# Endpoints that are not reachable from the ad account directly and have to be walked from a parent
# resource. `structured_posts` is the only one today: Reddit hangs creatives off the ad account's
# profiles, not off the account.
REDDIT_ADS_FANOUT: dict[str, DependentEndpointConfig] = {
    "structured_posts": DependentEndpointConfig(
        parent_name="profiles",
        resolve_param="profile_id",
        resolve_field="id",
        include_from_parent=["id"],
        # Post rows carry a nullable `profile_id`; the parent id we fetched under is authoritative.
        parent_field_renames={"id": "profile_id"},
    ),
}
