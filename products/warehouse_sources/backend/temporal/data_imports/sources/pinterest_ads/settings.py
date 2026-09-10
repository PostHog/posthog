from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.pinterest.com/v5"
PAGE_SIZE = 250
ANALYTICS_MAX_IDS = 250
ANALYTICS_MAX_DATE_RANGE_DAYS = 90
DEFAULT_LOOKBACK_DAYS = 89

# Pinterest Ads API v5 analytics columns
# Full column reference: https://developers.pinterest.com/docs/api/v5/ads-analytics/
ANALYTICS_COLUMNS = [
    # Spend
    # DOLLAR metrics use the advertiser's profile currency, not necessarily USD.
    # See https://developers.pinterest.com/docs/api/v5/ads-analytics/
    "SPEND_IN_DOLLAR",
    "SPEND_IN_MICRO_DOLLAR",
    # Impressions
    "PAID_IMPRESSION",
    "IMPRESSION_1",
    "IMPRESSION_2",
    "TOTAL_IMPRESSION",
    # Clicks
    "CLICKTHROUGH_1",
    "CLICKTHROUGH_2",
    "TOTAL_CLICKTHROUGH",
    "OUTBOUND_CLICK_1",
    # Engagement
    "TOTAL_ENGAGEMENT",
    "ENGAGEMENT_1",
    "ENGAGEMENT_2",
    "ENGAGEMENT_RATE",
    "EENGAGEMENT_RATE",  # not a typo — this is the actual Pinterest API column name
    "REPIN_RATE",
    # Rates
    "CTR",
    "ECTR",
    "CTR_2",
    "OUTBOUND_CTR_1",
    # Cost metrics
    "CPC_IN_MICRO_DOLLAR",
    "ECPC_IN_MICRO_DOLLAR",
    "ECPC_IN_DOLLAR",
    "ECPM_IN_MICRO_DOLLAR",
    "CPM_IN_MICRO_DOLLAR",
    "CPM_IN_DOLLAR",
    "ECPE_IN_DOLLAR",
    # Conversions
    "TOTAL_CONVERSIONS",
    "TOTAL_CHECKOUT",
    "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR",
    "CHECKOUT_ROAS",
    "TOTAL_SIGNUP",
    "TOTAL_LEAD",
    "TOTAL_PAGE_VISIT",
    # Video
    "TOTAL_VIDEO_3SEC_VIEWS",
    "TOTAL_VIDEO_MRC_VIEWS",
    "TOTAL_VIDEO_AVG_WATCHTIME_IN_SECOND",
    "TOTAL_VIDEO_P100_COMPLETE",
]


# Breakdown dimensions requested for the targeting analytics tables. Pinterest reports every
# requested targeting type independently within one response, and each value below is accepted at
# the campaign, ad group and ad level. High-cardinality types (KEYWORD, GEO, interests, audiences)
# are left out on purpose — they multiply row counts without answering the common questions.
# See https://developers.pinterest.com/docs/api/v5/campaign_targeting_analytics-get/
TARGETING_TYPES = [
    "AGE_BUCKET",
    "GENDER",
    "APPTYPE",
    "PLACEMENT",
    "COUNTRY",
    "REGION",
]


class EndpointType(str, Enum):
    ENTITY = "entity"
    ANALYTICS = "analytics"
    TARGETING_ANALYTICS = "targeting_analytics"


_DATE_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    }
]


@dataclass
class EndpointConfig:
    name: str
    primary_keys: list[str]
    endpoint_type: EndpointType
    # Empty keys with no mode means the endpoint has no stable timestamp to partition on.
    partition_keys: list[str] = field(default_factory=list)
    partition_mode: Optional[PartitionMode] = None
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1
    # Entity endpoints that return every row in one payload and reject bookmark pagination.
    supports_pagination: bool = True
    should_sync_default: bool = True
    # Endpoints that address a single resource by id and return that object directly, not an
    # `items` list. Fetched once and adapted into a one-row response.
    returns_single_object: bool = False


PINTEREST_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        name="campaigns",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_groups": EndpointConfig(
        name="ad_groups",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "ads": EndpointConfig(
        name="ads",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_accounts": EndpointConfig(
        name="ad_accounts",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
        supports_pagination=False,
        returns_single_object=True,
    ),
    "audiences": EndpointConfig(
        name="audiences",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_timestamp"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "conversion_tags": EndpointConfig(
        name="conversion_tags",
        primary_keys=["id"],
        incremental_fields=None,
        endpoint_type=EndpointType.ENTITY,
        supports_pagination=False,
    ),
    "keywords": EndpointConfig(
        name="keywords",
        primary_keys=["id"],
        incremental_fields=None,
        endpoint_type=EndpointType.ENTITY,
    ),
    "campaign_analytics": EndpointConfig(
        name="campaign_analytics",
        primary_keys=["campaign_id", "date"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
    "ad_group_analytics": EndpointConfig(
        name="ad_group_analytics",
        primary_keys=["ad_group_id", "date"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
    "ad_analytics": EndpointConfig(
        name="ad_analytics",
        primary_keys=["ad_id", "date"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
    # Breakdown tables fan out over every entity, every day and every targeting type, so they are
    # far larger than the totals tables and stay off by default.
    "campaign_targeting_analytics": EndpointConfig(
        name="campaign_targeting_analytics",
        primary_keys=["campaign_id", "date", "targeting_type", "targeting_value"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.TARGETING_ANALYTICS,
        should_sync_default=False,
    ),
    "ad_group_targeting_analytics": EndpointConfig(
        name="ad_group_targeting_analytics",
        primary_keys=["ad_group_id", "date", "targeting_type", "targeting_value"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.TARGETING_ANALYTICS,
        should_sync_default=False,
    ),
    "ad_targeting_analytics": EndpointConfig(
        name="ad_targeting_analytics",
        primary_keys=["ad_id", "date", "targeting_type", "targeting_value"],
        incremental_fields=_DATE_INCREMENTAL_FIELD,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.TARGETING_ANALYTICS,
        should_sync_default=False,
    ),
}

ENTITY_ENDPOINT_PATHS: dict[str, str] = {
    "campaigns": "/ad_accounts/{ad_account_id}/campaigns",
    "ad_groups": "/ad_accounts/{ad_account_id}/ad_groups",
    "ads": "/ad_accounts/{ad_account_id}/ads",
    # Scoped to the configured account so the source only ever imports metadata for the advertiser
    # it was created for, not every account the OAuth token can reach.
    "ad_accounts": "/ad_accounts/{ad_account_id}",
    "audiences": "/ad_accounts/{ad_account_id}/audiences",
    "conversion_tags": "/ad_accounts/{ad_account_id}/conversion_tags",
    "keywords": "/ad_accounts/{ad_account_id}/keywords",
}

ANALYTICS_ENDPOINT_PATHS: dict[str, str] = {
    "campaign_analytics": "/ad_accounts/{ad_account_id}/campaigns/analytics",
    "ad_group_analytics": "/ad_accounts/{ad_account_id}/ad_groups/analytics",
    "ad_analytics": "/ad_accounts/{ad_account_id}/ads/analytics",
}

TARGETING_ANALYTICS_ENDPOINT_PATHS: dict[str, str] = {
    "campaign_targeting_analytics": "/ad_accounts/{ad_account_id}/campaigns/targeting_analytics",
    "ad_group_targeting_analytics": "/ad_accounts/{ad_account_id}/ad_groups/targeting_analytics",
    "ad_targeting_analytics": "/ad_accounts/{ad_account_id}/ads/targeting_analytics",
}

# Targeting analytics rows only carry the metrics that were asked for, so the entity id has to be
# requested as a column to keep each row addressable back to its campaign / ad group / ad.
TARGETING_ANALYTICS_ID_COLUMNS: dict[str, str] = {
    "campaign_targeting_analytics": "CAMPAIGN_ID",
    "ad_group_targeting_analytics": "AD_GROUP_ID",
    "ad_targeting_analytics": "AD_ID",
}

ANALYTICS_ID_PARAM_NAMES: dict[str, str] = {
    "campaign_analytics": "campaign_ids",
    "ad_group_analytics": "ad_group_ids",
    "ad_analytics": "ad_ids",
    "campaign_targeting_analytics": "campaign_ids",
    "ad_group_targeting_analytics": "ad_group_ids",
    "ad_targeting_analytics": "ad_ids",
}

ANALYTICS_ENTITY_SOURCES: dict[str, str] = {
    "campaign_analytics": "campaigns",
    "ad_group_analytics": "ad_groups",
    "ad_analytics": "ads",
    "campaign_targeting_analytics": "campaigns",
    "ad_group_targeting_analytics": "ad_groups",
    "ad_targeting_analytics": "ads",
}
