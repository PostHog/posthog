# Marketing Analytics Constants and Configuration

# Magic values
DEFAULT_CURRENCY = 'USD'
DEFAULT_LIMIT = 100
PAGINATION_EXTRA = 1  # Request one extra for pagination
FALLBACK_COST_VALUE = 999999999
UNKNOWN_CAMPAIGN = 'Unknown Campaign'
UNKNOWN_SOURCE = 'Unknown Source'

# Table columns used in union queries
TABLE_COLUMNS = {
    'campaign_name': 'campaign_name',
    'source_name': 'source_name',
    'impressions': 'impressions',
    'clicks': 'clicks',
    'cost': 'cost',
}

# Final output columns
DEFAULT_MARKETING_ANALYTICS_COLUMNS = [
    "Campaign",
    "Source", 
    "Total Cost",
    "Total Clicks",
    "Total Impressions",
    "Cost per Click",
    "CTR"
]

# Marketing Analytics schema definition
MARKETING_ANALYTICS_SCHEMA = {
    'campaign_name': {'type': ['string'], 'required': True},
    'clicks': {'type': ['integer', 'number', 'float'], 'required': False},
    'currency': {'type': ['string'], 'required': False},
    'date': {'type': ['datetime', 'date', 'string'], 'required': True},
    'impressions': {'type': ['integer', 'number', 'float'], 'required': False},
    'source_name': {'type': ['string'], 'required': False},
    'total_cost': {'type': ['float', 'integer'], 'required': True},
    'utm_campaign_name': {'type': ['string'], 'required': False},
    'utm_source_name': {'type': ['string'], 'required': False},
}

# Valid native marketing sources
VALID_NATIVE_MARKETING_SOURCES = ['GoogleAds', 'MetaAds']

# Valid non-native marketing sources (managed external sources like BigQuery)
VALID_NON_NATIVE_MARKETING_SOURCES = ['BigQuery']

# Valid self-managed marketing sources (mirrors frontend types)
VALID_SELF_MANAGED_MARKETING_SOURCES = ['aws', 'google-cloud', 'cloudflare-r2', 'azure']

# Required tables for each native source
NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS = {
    'GoogleAds': ['campaign', 'campaign_stats'],
    'MetaAds': [],
} 