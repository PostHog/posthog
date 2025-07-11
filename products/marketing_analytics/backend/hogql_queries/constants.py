# Marketing Analytics Constants and Configuration

from posthog.schema import MarketingAnalyticsBaseColumns, MarketingAnalyticsColumnsSchemaNames
from posthog.hogql import ast

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

# Fields for the marketing analytics table aggregation select
TOTAL_COST_FIELD = "total_cost"
TOTAL_CLICKS_FIELD = "total_clicks"
TOTAL_IMPRESSIONS_FIELD = "total_impressions"

# Fallback query when no valid adapters are found
FALLBACK_EMPTY_QUERY = f"SELECT 'No Campaign' as {MarketingAnalyticsColumnsSchemaNames.CAMPAIGN}, 'No Source' as {MarketingAnalyticsColumnsSchemaNames.SOURCE}, 0.0 as {MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS}, 0.0 as {MarketingAnalyticsColumnsSchemaNames.CLICKS}, 0.0 as {MarketingAnalyticsColumnsSchemaNames.COST} WHERE 1=0"


# Final output columns
DEFAULT_MARKETING_ANALYTICS_COLUMNS = list(MarketingAnalyticsBaseColumns)

# AST Expression mappings for MarketingAnalyticsBaseColumns
BASE_COLUMN_MAPPING = {
    MarketingAnalyticsBaseColumns.CAMPAIGN: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.CAMPAIGN,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.CAMPAIGN]),
    ),
    MarketingAnalyticsBaseColumns.SOURCE: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.SOURCE,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.SOURCE]),
    ),
    MarketingAnalyticsBaseColumns.TOTAL_COST: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.TOTAL_COST,
        expr=ast.Call(
            name="round",
            args=[
                ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
    MarketingAnalyticsBaseColumns.TOTAL_CLICKS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.TOTAL_CLICKS,
        expr=ast.Call(
            name="round",
            args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]), ast.Constant(value=0)],
        ),
    ),
    MarketingAnalyticsBaseColumns.TOTAL_IMPRESSIONS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.TOTAL_IMPRESSIONS,
        expr=ast.Call(
            name="round",
            args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_IMPRESSIONS_FIELD]), ast.Constant(value=0)],
        ),
    ),
    MarketingAnalyticsBaseColumns.COST_PER_CLICK: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.COST_PER_CLICK,
        expr=ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(
                        name="nullif",
                        args=[
                            ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
    MarketingAnalyticsBaseColumns.CTR: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.CTR,
        expr=ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]),
                        op=ast.ArithmeticOperationOp.Div,
                        right=ast.Call(
                            name="nullif",
                            args=[
                                ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_IMPRESSIONS_FIELD]),
                                ast.Constant(value=0),
                            ],
                        ),
                    ),
                    op=ast.ArithmeticOperationOp.Mult,
                    right=ast.Constant(value=CTR_PERCENTAGE_MULTIPLIER),
                ),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
}

BASE_COLUMNS = [BASE_COLUMN_MAPPING[column] for column in MarketingAnalyticsBaseColumns]

# Marketing Analytics schema definition. This is the schema that is used to validate the source map.
MARKETING_ANALYTICS_SCHEMA = {
    MarketingAnalyticsColumnsSchemaNames.CAMPAIGN: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.SOURCE: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.CLICKS: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.COST: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.DATE: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.CURRENCY: {"required": False},
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
