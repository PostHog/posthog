from enum import StrEnum
from typing import Literal, NotRequired, TypedDict

from products.warehouse_sources.backend.types import IncrementalFieldType

# adAnalytics metrics, coerced to a stable python type on every row (see `_coerce_metric`).
# LinkedIn omits a metric entirely when its value is zero and can flip a metric between JSON number
# and string across pages, so an uncoerced column's arrow type varies per batch. Batches are type-
# inferred independently, and a batch where a metric was omitted for every row infers as `null`,
# which the Delta-compat cast rewrites to `string` — that batch then fails to merge with a numeric
# one. Coercing here (including absent → 0) keeps each column's type identical across every batch.
FLOAT_FIELDS = {"costInUsd", "costInLocalCurrency", "conversionValueInLocalCurrency"}

INT_FIELDS = {
    "impressions",
    "clicks",
    "externalWebsiteConversions",
    "landingPageClicks",
    "totalEngagements",
    "videoViews",
    "videoCompletions",
    "oneClickLeads",
    "follows",
}

# There are in the results from the API. The value is in the URN format.
URN_COLUMNS = ["campaignGroup", "account", "campaign", "creative"]

# Fields LinkedIn returns as epoch-millisecond longs, and the date column each one flattens into.
# The ad entity finders use `createdAt`/`lastModifiedAt`; the conversions finder uses the shorter
# `created`/`lastModified` names for the same thing.
EPOCH_MS_VIRTUAL_COLUMNS = {
    "createdAt": "created_time",
    "lastModifiedAt": "last_modified_time",
    "created": "created_time",
    "lastModified": "last_modified_time",
}

# This maps the the URN type to the virtual column name. LinkedIn Ads API uses URNs to identify resources.
# URNs are like "urn:li:sponsoredCampaign:12345678"
VIRTUAL_COLUMN_URN_MAPPING = {
    "sponsoredCampaign": "campaign_id",
    "sponsoredCampaignGroup": "campaign_group_id",
    "sponsoredAccount": "account_id",
    "sponsoredCreative": "creative_id",
}


class LinkedinAdsResource(StrEnum):
    Accounts = "accounts"
    Campaigns = "campaigns"
    CampaignGroups = "campaign_groups"
    Creatives = "creatives"
    Conversions = "conversions"
    CampaignStats = "campaign_stats"
    CampaignGroupStats = "campaign_group_stats"
    CreativeStats = "creative_stats"
    MemberCompanyStats = "member_company_stats"
    MemberCompanySizeStats = "member_company_size_stats"
    MemberCountryStats = "member_country_stats"
    MemberIndustryStats = "member_industry_stats"
    MemberJobTitleStats = "member_job_title_stats"
    MemberSeniorityStats = "member_seniority_stats"


class LinkedinAdsPivot(StrEnum):
    ACCOUNT = "ACCOUNT"
    CAMPAIGN = "CAMPAIGN"
    CAMPAIGN_GROUP = "CAMPAIGN_GROUP"
    CREATIVE = "CREATIVE"
    MEMBER_COMPANY = "MEMBER_COMPANY"
    MEMBER_COMPANY_SIZE = "MEMBER_COMPANY_SIZE"
    MEMBER_COUNTRY_V2 = "MEMBER_COUNTRY_V2"
    MEMBER_INDUSTRY = "MEMBER_INDUSTRY"
    MEMBER_JOB_TITLE = "MEMBER_JOB_TITLE"
    MEMBER_SENIORITY = "MEMBER_SENIORITY"


# LinkedIn API endpoint mappings
LINKEDIN_ADS_ENDPOINTS = {
    LinkedinAdsResource.Accounts: "adAccounts",
    LinkedinAdsResource.Campaigns: "adCampaigns",
    LinkedinAdsResource.CampaignGroups: "adCampaignGroups",
    LinkedinAdsResource.Creatives: "creatives",
    LinkedinAdsResource.Conversions: "conversions",
    LinkedinAdsResource.CampaignStats: "adAnalytics",
    LinkedinAdsResource.CampaignGroupStats: "adAnalytics",
    LinkedinAdsResource.CreativeStats: "adAnalytics",
    LinkedinAdsResource.MemberCompanyStats: "adAnalytics",
    LinkedinAdsResource.MemberCompanySizeStats: "adAnalytics",
    LinkedinAdsResource.MemberCountryStats: "adAnalytics",
    LinkedinAdsResource.MemberIndustryStats: "adAnalytics",
    LinkedinAdsResource.MemberJobTitleStats: "adAnalytics",
    LinkedinAdsResource.MemberSeniorityStats: "adAnalytics",
}

# Pivot mappings for analytics resources
LINKEDIN_ADS_PIVOTS = {
    LinkedinAdsResource.CampaignStats: LinkedinAdsPivot.CAMPAIGN,
    LinkedinAdsResource.CampaignGroupStats: LinkedinAdsPivot.CAMPAIGN_GROUP,
    LinkedinAdsResource.CreativeStats: LinkedinAdsPivot.CREATIVE,
    LinkedinAdsResource.MemberCompanyStats: LinkedinAdsPivot.MEMBER_COMPANY,
    LinkedinAdsResource.MemberCompanySizeStats: LinkedinAdsPivot.MEMBER_COMPANY_SIZE,
    LinkedinAdsResource.MemberCountryStats: LinkedinAdsPivot.MEMBER_COUNTRY_V2,
    LinkedinAdsResource.MemberIndustryStats: LinkedinAdsPivot.MEMBER_INDUSTRY,
    LinkedinAdsResource.MemberJobTitleStats: LinkedinAdsPivot.MEMBER_JOB_TITLE,
    LinkedinAdsResource.MemberSeniorityStats: LinkedinAdsPivot.MEMBER_SENIORITY,
}


class ResourceSchema(TypedDict):
    resource_name: str
    field_names: list[str]
    primary_key: list[str]
    filter_field_names: NotRequired[list[tuple[str, IncrementalFieldType]]]
    partition_keys: list[str]
    partition_mode: Literal["md5", "numerical", "datetime"] | None
    partition_format: Literal["month", "week", "day"] | None
    partition_size: int
    is_stats: bool
    # Column the raw first entry of `pivotValues` is written to, for pivots whose value is not a
    # sponsored-entity URN we already flatten into an `*_id` column (the professional demographic
    # pivots). Doubles as part of the primary key for those tables.
    pivot_value_column: NotRequired[str]
    # Overrides the source-wide initial analytics lookback for resources with shorter retention.
    initial_lookback_days: NotRequired[int]
    # False leaves the table unticked in the schema picker.
    should_sync_default: NotRequired[bool]


# LinkedIn retains professional demographic reporting for two years, versus ten for performance
# reporting, and rejects a start date outside the retention window with a 400 (DATE_TOO_EARLY).
DEMOGRAPHIC_RETENTION_DAYS = 365 * 2

# Metrics requested for a professional demographic pivot. Same list as the performance stats
# resources minus `conversionValueInLocalCurrency`, which LinkedIn documents as available for
# non-demographic pivots only.
DEMOGRAPHIC_STATS_FIELD_NAMES = [
    "impressions",
    "clicks",
    "dateRange",
    "pivotValues",
    "costInUsd",
    "costInLocalCurrency",
    "externalWebsiteConversions",
    "landingPageClicks",
    "totalEngagements",
    "videoViews",
    "videoCompletions",
    "oneClickLeads",
    "follows",
]

# Column holding the raw demographic pivot URN (e.g. `urn:li:industry:96`). Kept as the raw string
# because the id segment is only numeric for some pivots — MEMBER_COMPANY_SIZE returns a named
# size bucket — and there is no table in this source to join a parsed id against.
DEMOGRAPHIC_PIVOT_COLUMN = "pivot_value"


def _demographic_stats_schema(resource_name: str) -> "ResourceSchema":
    return {
        "resource_name": resource_name,
        "field_names": DEMOGRAPHIC_STATS_FIELD_NAMES.copy(),
        "primary_key": ["date_start", "date_end", DEMOGRAPHIC_PIVOT_COLUMN],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
        "pivot_value_column": DEMOGRAPHIC_PIVOT_COLUMN,
        "initial_lookback_days": DEMOGRAPHIC_RETENTION_DAYS,
        # One row per (day × demographic value) on top of the performance tables, and only useful
        # to advertisers who report on audience makeup, so it stays off unless asked for.
        "should_sync_default": False,
    }


# LinkedIn Ads resource schemas
RESOURCE_SCHEMAS: dict[LinkedinAdsResource, ResourceSchema] = {
    LinkedinAdsResource.Accounts: {
        "resource_name": "accounts",
        "field_names": ["id", "name", "status", "type", "currency", "version"],
        "primary_key": ["id"],
        "partition_keys": ["id"],
        "partition_mode": "numerical",
        "partition_format": None,
        "is_stats": False,
        "partition_size": 1000,
    },
    LinkedinAdsResource.Campaigns: {
        "resource_name": "campaigns",
        "field_names": [
            "id",
            "name",
            "account",
            "campaignGroup",
            "status",
            "type",
            "changeAuditStamps",
            "runSchedule",
            "dailyBudget",
            "unitCost",
            "costType",
            "targetingCriteria",
            "locale",
            "version",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignGroups: {
        "resource_name": "campaign_groups",
        "field_names": [
            "id",
            "name",
            "account",
            "status",
            "runSchedule",
            "totalBudget",
            "changeAuditStamps",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.Creatives: {
        "resource_name": "creatives",
        # CreativeV11 rejects `type` and `changeAuditStamps` — don't add them here.
        "field_names": [
            "id",
            "account",
            "campaign",
            "name",
            "intendedStatus",
            "isServing",
            "review",
            "createdAt",
            "lastModifiedAt",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.Conversions: {
        "resource_name": "conversions",
        "field_names": [
            "id",
            "name",
            "type",
            "enabled",
            "account",
            "campaigns",
            "attributionType",
            "conversionMethod",
            "postClickAttributionWindowSize",
            "viewThroughAttributionWindowSize",
            "value",
            "created",
            "lastModified",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignStats: {
        "resource_name": "campaign_stats",
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "campaign_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignGroupStats: {
        "resource_name": "campaign_group_stats",
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "campaign_group_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
    },
    LinkedinAdsResource.CreativeStats: {
        "resource_name": "creative_stats",
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "creative_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
    },
    LinkedinAdsResource.MemberCompanyStats: _demographic_stats_schema("member_company_stats"),
    LinkedinAdsResource.MemberCompanySizeStats: _demographic_stats_schema("member_company_size_stats"),
    LinkedinAdsResource.MemberCountryStats: _demographic_stats_schema("member_country_stats"),
    LinkedinAdsResource.MemberIndustryStats: _demographic_stats_schema("member_industry_stats"),
    LinkedinAdsResource.MemberJobTitleStats: _demographic_stats_schema("member_job_title_stats"),
    LinkedinAdsResource.MemberSeniorityStats: _demographic_stats_schema("member_seniority_stats"),
}
