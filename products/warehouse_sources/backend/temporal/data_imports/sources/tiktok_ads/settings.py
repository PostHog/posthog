import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MAX_TIKTOK_DAYS_TO_QUERY = 29
BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"
MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS = 365

METRICS_FIELDS = [
    "app_promotion_type",
    "average_video_play_per_user",
    "average_video_play",
    "billing_event",
    "campaign_budget",
    "campaign_dedicate_type",
    "campaign_name",
    "clicks_on_music_disc",
    "clicks",
    "comments",
    "conversion_rate_v2",
    "conversion_rate",
    "conversion",
    "complete_payment",
    "total_complete_payment_rate",
    "cost_per_1000_reached",
    "cost_per_conversion",
    "cost_per_result",
    "cost_per_secondary_goal_result",
    "cpc",
    "cpm",
    "ctr",
    "currency",
    "follows",
    "frequency",
    "gross_impressions",
    "impressions",
    "likes",
    "profile_visits_rate",
    "profile_visits",
    "reach",
    "real_time_conversion_rate_v2",
    "real_time_conversion_rate",
    "real_time_conversion",
    "real_time_cost_per_conversion",
    "real_time_cost_per_result",
    "real_time_result_rate",
    "real_time_result",
    "result_rate",
    "result",
    "secondary_goal_result_rate",
    "secondary_goal_result",
    "shares",
    "spend",
    "split_test",
    "video_play_actions",
    "video_views_p100",
    "video_views_p25",
    "video_views_p50",
    "video_views_p75",
    "video_watched_2s",
    "video_watched_6s",
]

TIKTOK_REPORT_METRICS = json.dumps(METRICS_FIELDS)

# Metrics TikTok accepts on an AUDIENCE report. Narrower than the BASIC set above:
# account/entity attributes such as `currency`, `campaign_budget`, `billing_event` and
# `split_test` are not available once the report is broken down by an audience dimension.
AUDIENCE_REPORT_METRICS_FIELDS = [
    "average_video_play_per_user",
    "average_video_play",
    "clicks_on_music_disc",
    "clicks",
    "comments",
    "cost_per_1000_reached",
    "cpc",
    "cpm",
    "ctr",
    "follows",
    "frequency",
    "impressions",
    "likes",
    "profile_visits",
    "reach",
    "shares",
    "spend",
    "video_play_actions",
    "video_views_p100",
    "video_views_p25",
    "video_views_p50",
    "video_views_p75",
    "video_watched_2s",
    "video_watched_6s",
]

# Conversion metrics TikTok only reports below campaign level on an AUDIENCE report.
_AUDIENCE_CONVERSION_METRICS_FIELDS = [
    "conversion_rate",
    "conversion",
    "cost_per_conversion",
    "cost_per_result",
    "real_time_conversion_rate",
    "real_time_conversion",
    "real_time_cost_per_conversion",
    "real_time_cost_per_result",
    "real_time_result_rate",
    "real_time_result",
    "result_rate",
    "result",
]

CAMPAIGN_AUDIENCE_REPORT_METRICS_FIELDS = [*AUDIENCE_REPORT_METRICS_FIELDS, "campaign_name"]
AD_GROUP_AUDIENCE_REPORT_METRICS_FIELDS = [
    *AUDIENCE_REPORT_METRICS_FIELDS,
    *_AUDIENCE_CONVERSION_METRICS_FIELDS,
    "adgroup_name",
    "campaign_id",
    "campaign_name",
    "placement_type",
    "promotion_type",
]
AD_AUDIENCE_REPORT_METRICS_FIELDS = [
    *AD_GROUP_AUDIENCE_REPORT_METRICS_FIELDS,
    "ad_name",
    "ad_text",
    "adgroup_id",
]

ENDPOINT_ADVERTISERS = ["advertisers"]
ENDPOINT_AD_MANAGEMENT = ["campaigns", "adgroups", "ads"]
ENDPOINT_INSIGHTS = ["campaign_report", "ad_group_report", "ad_report"]


class EndpointType(str, Enum):
    ACCOUNT = "account"
    ENTITY = "entity"
    REPORT = "report"
    # Creative library assets (videos, images). Unlike ENTITY rows they carry no
    # operational status and no comment settings, so they pass through untransformed.
    ASSET = "asset"


@dataclass
class EndpointConfig:
    partition_keys: list[str]
    partition_mode: PartitionMode
    resource: EndpointResource
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1
    endpoint_type: Optional[EndpointType] = None
    should_sync_default: bool = True


STAT_TIME_DAY_INCREMENTAL_FIELD: IncrementalField = {
    "label": "stat_time_day",
    "type": IncrementalFieldType.Date,
    "field": "stat_time_day",
    "field_type": IncrementalFieldType.Date,
}


def audience_report_config(name: str, data_level: str, dimensions: list[str], metrics: list[str]) -> EndpointConfig:
    """One AUDIENCE-report breakdown table.

    Same `/report/integrated/get/` endpoint as the existing BASIC report tables, with
    `report_type=AUDIENCE` and the breakdown appended to `dimensions`. TikTok returns one
    row per (entity, day, breakdown value), so the dimension list is also the primary key.

    Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
    """
    return EndpointConfig(
        resource={
            "name": name,
            "table_name": name,
            "primary_key": dimensions,
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "AUDIENCE",
                    "data_level": data_level,
                    "dimensions": json.dumps(dimensions),
                    "metrics": json.dumps(metrics),
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[STAT_TIME_DAY_INCREMENTAL_FIELD],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
        # A breakdown multiplies every entity-day by its distinct dimension values, so these
        # are far larger than the totals tables and only some accounts care about them.
        should_sync_default=False,
    )


TIKTOK_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        resource={
            # Docs: https://business-api.tiktok.com/portal/docs?id=1739315828649986
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": ["campaign_id"],
            "endpoint": {
                "path": "/campaign/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_groups": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1739314558673922
        resource={
            "name": "ad_groups",
            "table_name": "ad_groups",
            "primary_key": ["adgroup_id"],
            "endpoint": {
                "path": "/adgroup/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ads": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1735735588640770
        resource={
            "name": "ads",
            "table_name": "ads",
            "primary_key": ["ad_id"],
            "endpoint": {
                "path": "/ad/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "campaign_report": EndpointConfig(
        resource={
            # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
            "name": "campaign_report",
            "table_name": "campaign_report",
            "primary_key": ["campaign_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_CAMPAIGN",
                    "dimensions": '["campaign_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
    "ad_group_report": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
        resource={
            "name": "ad_group_report",
            "table_name": "ad_group_report",
            "primary_key": ["adgroup_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_ADGROUP",
                    "dimensions": '["adgroup_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
    "ad_report": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
        resource={
            "name": "ad_report",
            "table_name": "ad_report",
            "primary_key": ["ad_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_AD",
                    "dimensions": '["ad_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
    "creative_videos": EndpointConfig(
        resource={
            # TikTok creative library, video assets. Docs: https://business-api.tiktok.com/portal/docs
            "name": "creative_videos",
            "table_name": "creative_videos",
            "primary_key": ["video_id"],
            "endpoint": {
                "path": "/file/video/ad/search/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    # TikTok caps the creative library search at 100 per page.
                    "page_size": 100,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        # `modify_time` is only filterable client-side, so this stays full refresh.
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ASSET,
        # Creative asset access is a separate grant most advertisers don't give, and the denial
        # only surfaces once a sync has run. Opt-in keeps that failure out of a first-time setup.
        should_sync_default=False,
    ),
    "creative_images": EndpointConfig(
        resource={
            # TikTok creative library, image assets. Docs: https://business-api.tiktok.com/portal/docs
            "name": "creative_images",
            "table_name": "creative_images",
            "primary_key": ["image_id"],
            "endpoint": {
                "path": "/file/image/ad/search/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 100,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ASSET,
        should_sync_default=False,
    ),
    "campaign_demographic_report": audience_report_config(
        "campaign_demographic_report",
        "AUCTION_CAMPAIGN",
        ["campaign_id", "stat_time_day", "gender", "age"],
        CAMPAIGN_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "campaign_country_report": audience_report_config(
        "campaign_country_report",
        "AUCTION_CAMPAIGN",
        ["campaign_id", "stat_time_day", "country_code"],
        CAMPAIGN_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "campaign_platform_report": audience_report_config(
        "campaign_platform_report",
        "AUCTION_CAMPAIGN",
        ["campaign_id", "stat_time_day", "platform"],
        CAMPAIGN_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_group_demographic_report": audience_report_config(
        "ad_group_demographic_report",
        "AUCTION_ADGROUP",
        ["adgroup_id", "stat_time_day", "gender", "age"],
        AD_GROUP_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_group_country_report": audience_report_config(
        "ad_group_country_report",
        "AUCTION_ADGROUP",
        ["adgroup_id", "stat_time_day", "country_code"],
        AD_GROUP_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_group_platform_report": audience_report_config(
        "ad_group_platform_report",
        "AUCTION_ADGROUP",
        ["adgroup_id", "stat_time_day", "platform"],
        AD_GROUP_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_demographic_report": audience_report_config(
        "ad_demographic_report",
        "AUCTION_AD",
        ["ad_id", "stat_time_day", "gender", "age"],
        AD_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_country_report": audience_report_config(
        "ad_country_report",
        "AUCTION_AD",
        ["ad_id", "stat_time_day", "country_code"],
        AD_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
    "ad_platform_report": audience_report_config(
        "ad_platform_report",
        "AUCTION_AD",
        ["ad_id", "stat_time_day", "platform"],
        AD_AUDIENCE_REPORT_METRICS_FIELDS,
    ),
}
