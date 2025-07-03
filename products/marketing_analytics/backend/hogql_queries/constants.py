# Marketing Analytics Constants and Configuration

# Magic values
DEFAULT_LIMIT = 100
PAGINATION_EXTRA = 1  # Request one extra for pagination
FALLBACK_COST_VALUE = 999999999
UNKNOWN_CAMPAIGN = "Unknown Campaign"
UNKNOWN_SOURCE = "Unknown Source"
CTR_PERCENTAGE_MULTIPLIER = 100
DECIMAL_PRECISION = 2

# CTE names
CAMPAIGN_COST_CTE_NAME = "campaign_costs"

# Prefixes for table names
CONVERSION_GOAL_PREFIX_ABBREVIATION = "cg_"
CONVERSION_GOAL_PREFIX = "conversion_"

# Fields for the marketing analytics table select
CAMPAIGN_NAME_FIELD = "campaign_name"
SOURCE_NAME_FIELD = "source_name"
IMPRESSIONS_FIELD = "impressions"
CLICKS_FIELD = "clicks"
COST_FIELD = "cost"
TOTAL_COST_FIELD = "total_cost"
TOTAL_CLICKS_FIELD = "total_clicks"
TOTAL_IMPRESSIONS_FIELD = "total_impressions"

# Fallback query when no valid adapters are found
FALLBACK_EMPTY_QUERY = f"SELECT 'No Campaign' as {CAMPAIGN_NAME_FIELD}, 'No Source' as {SOURCE_NAME_FIELD}, 0.0 as impressions, 0.0 as clicks, 0.0 as cost WHERE 1=0"


# Final output columns
DEFAULT_MARKETING_ANALYTICS_COLUMNS = [
    "Campaign",
    "Source",
    "Total Cost",
    "Total Clicks",
    "Total Impressions",
    "Cost per Click",
    "CTR",
]

# This matches the source map schema in the frontend
SOURCE_MAP_CAMPAIGN_NAME = "campaign_name"
SOURCE_MAP_CLICKS = "clicks"
SOURCE_MAP_COST = "cost"
SOURCE_MAP_DATE = "date"
SOURCE_MAP_IMPRESSIONS = "impressions"
SOURCE_MAP_SOURCE_NAME = "source_name"
SOURCE_MAP_TOTAL_COST = "total_cost"
SOURCE_MAP_UTM_CAMPAIGN_NAME = "utm_campaign_name"
SOURCE_MAP_UTM_SOURCE_NAME = "utm_source_name"
SOURCE_MAP_CURRENCY = "currency"

# Marketing Analytics schema definition. This is the schema that is used to validate the source map.
MARKETING_ANALYTICS_SCHEMA = {
    SOURCE_MAP_CAMPAIGN_NAME: {"required": True},
    SOURCE_MAP_CLICKS: {"required": False},
    SOURCE_MAP_COST: {"required": False},
    SOURCE_MAP_DATE: {"required": True},
    SOURCE_MAP_IMPRESSIONS: {"required": False},
    SOURCE_MAP_SOURCE_NAME: {"required": False},
    SOURCE_MAP_TOTAL_COST: {"required": True},
    SOURCE_MAP_UTM_CAMPAIGN_NAME: {"required": False},
    SOURCE_MAP_UTM_SOURCE_NAME: {"required": False},
    SOURCE_MAP_CURRENCY: {"required": False},
}

# Valid native marketing sources
VALID_NATIVE_MARKETING_SOURCES = ["GoogleAds"]

# Valid non-native marketing sources (managed external sources like BigQuery)
VALID_NON_NATIVE_MARKETING_SOURCES = ["BigQuery"]

# Valid self-managed marketing sources (mirrors frontend types)
VALID_SELF_MANAGED_MARKETING_SOURCES = ["aws", "google-cloud", "cloudflare-r2", "azure"]

# Required tables for each native source
NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS = {
    "GoogleAds": ["campaign", "campaign_stats"],
}

# Table pattern matching for native sources. TODO: find a better way to get the table names from the source.
TABLE_PATTERNS = {
    "GoogleAds": {
        "campaign_table_keywords": ["campaign"],
        "campaign_table_exclusions": ["stats"],
        "stats_table_keywords": ["campaign_stats"],
    },
}
