# Marketing Analytics Constants and Configuration

import math
from typing import Optional, Union

from pydantic import BaseModel

from posthog.schema import (
    BingAdsDefaultSources,
    BingAdsTableExclusions,
    BingAdsTableKeywords,
    GoogleAdsDefaultSources,
    GoogleAdsTableExclusions,
    GoogleAdsTableKeywords,
    InfinityValue,
    LinkedinAdsDefaultSources,
    LinkedinAdsTableExclusions,
    LinkedinAdsTableKeywords,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsItem,
    MarketingIntegrationConfig1,
    MarketingIntegrationConfig2,
    MarketingIntegrationConfig3,
    MarketingIntegrationConfig4,
    MarketingIntegrationConfig5,
    MarketingIntegrationConfig6,
    MetaAdsDefaultSources,
    MetaAdsTableExclusions,
    MetaAdsTableKeywords,
    NativeMarketingSource,
    RedditAdsDefaultSources,
    RedditAdsTableExclusions,
    RedditAdsTableKeywords,
    TikTokAdsDefaultSources,
    TikTokAdsTableExclusions,
    TikTokAdsTableKeywords,
    WebAnalyticsItemKind,
)

from posthog.hogql import ast

# Magic values
DEFAULT_LIMIT = 100
PAGINATION_EXTRA = 1  # Request one extra for pagination
FALLBACK_COST_VALUE = 999999999
UNKNOWN_CAMPAIGN = "Unknown Campaign"
UNKNOWN_SOURCE = "Unknown Source"
ORGANIC_CAMPAIGN = "organic"
ORGANIC_SOURCE = "organic"
CTR_PERCENTAGE_MULTIPLIER = 100
DECIMAL_PRECISION = 2
DEFAULT_DISTINCT_ID_FIELD = "distinct_id"

# CTE names
CAMPAIGN_COST_CTE_NAME = "campaign_costs"
UNIFIED_CONVERSION_GOALS_CTE_ALIAS = "ucg"

# Prefixes for table names
CONVERSION_GOAL_PREFIX_ABBREVIATION = "cg_"
CONVERSION_GOAL_PREFIX = "conversion_"

# Fields for the marketing analytics table aggregation select
TOTAL_COST_FIELD = "total_cost"
TOTAL_CLICKS_FIELD = "total_clicks"
TOTAL_IMPRESSIONS_FIELD = "total_impressions"
TOTAL_REPORTED_CONVERSION_FIELD = "total_reported_conversions"
TOTAL_REPORTED_CONVERSION_VALUE_FIELD = "total_reported_conversion_value"

# Field used for joining with conversion goals
MATCH_KEY_FIELD = "match_key"

# Fallback query when no valid adapters are found (includes all 9 columns in correct order)
# Order: match_key, campaign, id, source, impressions, clicks, cost, reported_conversion, reported_conversion_value
FALLBACK_EMPTY_QUERY = (
    f"SELECT '' as {MATCH_KEY_FIELD}, "
    f"'No Campaign' as {MarketingAnalyticsColumnsSchemaNames.CAMPAIGN}, "
    f"'No ID' as {MarketingAnalyticsColumnsSchemaNames.ID}, "
    f"'No Source' as {MarketingAnalyticsColumnsSchemaNames.SOURCE}, "
    f"0.0 as {MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS}, "
    f"0.0 as {MarketingAnalyticsColumnsSchemaNames.CLICKS}, "
    f"0.0 as {MarketingAnalyticsColumnsSchemaNames.COST}, "
    f"0.0 as {MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION}, "
    f"0.0 as {MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION_VALUE} "
    "WHERE 1=0"
)

# AST Expression mappings for MarketingAnalyticsBaseColumns
BASE_COLUMN_MAPPING = {
    MarketingAnalyticsBaseColumns.ID: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.ID,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.ID]),
    ),
    MarketingAnalyticsBaseColumns.CAMPAIGN: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.CAMPAIGN,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.CAMPAIGN]),
    ),
    MarketingAnalyticsBaseColumns.SOURCE: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.SOURCE,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.SOURCE]),
    ),
    MarketingAnalyticsBaseColumns.COST: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.COST,
        expr=ast.Call(
            name="round",
            args=[
                ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
    MarketingAnalyticsBaseColumns.CLICKS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.CLICKS,
        expr=ast.Call(
            name="round",
            args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_CLICKS_FIELD]), ast.Constant(value=0)],
        ),
    ),
    MarketingAnalyticsBaseColumns.IMPRESSIONS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.IMPRESSIONS,
        expr=ast.Call(
            name="round",
            args=[ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_IMPRESSIONS_FIELD]), ast.Constant(value=0)],
        ),
    ),
    MarketingAnalyticsBaseColumns.CPC: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.CPC,
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
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.REPORTED_CONVERSION,
        expr=ast.Call(
            name="round",
            args=[
                ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_REPORTED_CONVERSION_FIELD]),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE,
        expr=ast.Call(
            name="round",
            args=[
                ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_REPORTED_CONVERSION_VALUE_FIELD]),
                ast.Constant(value=DECIMAL_PRECISION),
            ],
        ),
    ),
    MarketingAnalyticsBaseColumns.REPORTED_ROAS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.REPORTED_ROAS,
        expr=ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_REPORTED_CONVERSION_VALUE_FIELD]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(
                        name="nullif",
                        args=[
                            ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                            ast.Constant(value=0),
                        ],
                    ),
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
    MarketingAnalyticsColumnsSchemaNames.ID: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.SOURCE: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.CLICKS: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.COST: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.DATE: {"required": True},
    MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.CURRENCY: {"required": False},
}

# Valid native marketing sources - derived from generated enum
VALID_NATIVE_MARKETING_SOURCES = [source.value for source in NativeMarketingSource]

# Valid non-native marketing sources (managed external sources like BigQuery)
VALID_NON_NATIVE_MARKETING_SOURCES = ["BigQuery"]

# Valid self-managed marketing sources (mirrors frontend types)
VALID_SELF_MANAGED_MARKETING_SOURCES = ["aws", "google-cloud", "cloudflare-r2", "azure"]

# Map generated config models to NativeMarketingSource using sourceType field
_ALL_CONFIG_MODELS = [
    MarketingIntegrationConfig1,
    MarketingIntegrationConfig2,
    MarketingIntegrationConfig3,
    MarketingIntegrationConfig4,
    MarketingIntegrationConfig5,
    MarketingIntegrationConfig6,
]


def _get_field_default(model: type[BaseModel], field_name: str):
    """Extract default value from a Pydantic model field."""
    return model.model_fields[field_name].default


# Build mapping from NativeMarketingSource to config model using sourceType
_CONFIG_MODELS: dict[NativeMarketingSource, type] = {}
for _config in _ALL_CONFIG_MODELS:
    _source_type_value = _get_field_default(_config, "sourceType")
    _source = NativeMarketingSource(_source_type_value)
    _CONFIG_MODELS[_source] = _config


def _get_enum_values(enum_class) -> list[str]:
    """Extract values from a StrEnum or RootModel literal type."""
    # Check if it's a StrEnum (has __members__)
    if hasattr(enum_class, "__members__"):
        return [member.value for member in enum_class]
    # It's a RootModel with a single literal value - get the default
    if hasattr(enum_class, "model_fields") and "root" in enum_class.model_fields:
        return [enum_class.model_fields["root"].default]
    return []


# Mapping from NativeMarketingSource to generated enum types
_DEFAULT_SOURCES_ENUMS = {
    NativeMarketingSource.GOOGLE_ADS: GoogleAdsDefaultSources,
    NativeMarketingSource.LINKEDIN_ADS: LinkedinAdsDefaultSources,
    NativeMarketingSource.META_ADS: MetaAdsDefaultSources,
    NativeMarketingSource.TIK_TOK_ADS: TikTokAdsDefaultSources,
    NativeMarketingSource.REDDIT_ADS: RedditAdsDefaultSources,
    NativeMarketingSource.BING_ADS: BingAdsDefaultSources,
}

_TABLE_KEYWORDS_ENUMS = {
    NativeMarketingSource.GOOGLE_ADS: GoogleAdsTableKeywords,
    NativeMarketingSource.LINKEDIN_ADS: LinkedinAdsTableKeywords,
    NativeMarketingSource.META_ADS: MetaAdsTableKeywords,
    NativeMarketingSource.TIK_TOK_ADS: TikTokAdsTableKeywords,
    NativeMarketingSource.REDDIT_ADS: RedditAdsTableKeywords,
    NativeMarketingSource.BING_ADS: BingAdsTableKeywords,
}

_TABLE_EXCLUSIONS_ENUMS = {
    NativeMarketingSource.GOOGLE_ADS: GoogleAdsTableExclusions,
    NativeMarketingSource.LINKEDIN_ADS: LinkedinAdsTableExclusions,
    NativeMarketingSource.META_ADS: MetaAdsTableExclusions,
    NativeMarketingSource.TIK_TOK_ADS: TikTokAdsTableExclusions,
    NativeMarketingSource.REDDIT_ADS: RedditAdsTableExclusions,
    NativeMarketingSource.BING_ADS: BingAdsTableExclusions,
}

# Derived constants from generated types
NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS = {
    source: [
        _get_field_default(config, "campaignTableName"),
        _get_field_default(config, "statsTableName"),
    ]
    for source, config in _CONFIG_MODELS.items()
}

TABLE_PATTERNS = {
    source: {
        "campaign_table_keywords": _get_enum_values(_TABLE_KEYWORDS_ENUMS[source]),
        "campaign_table_exclusions": _get_enum_values(_TABLE_EXCLUSIONS_ENUMS[source]),
        "stats_table_keywords": [_get_field_default(config, "statsTableName")],
    }
    for source, config in _CONFIG_MODELS.items()
}

INTEGRATION_FIELD_NAMES = {
    source: {
        "name_field": _get_field_default(config, "nameField"),
        "id_field": _get_field_default(config, "idField"),
    }
    for source, config in _CONFIG_MODELS.items()
}

INTEGRATION_PRIMARY_SOURCE = {
    source: _get_field_default(config, "primarySource") for source, config in _CONFIG_MODELS.items()
}

INTEGRATION_DEFAULT_SOURCES = {
    source: _get_enum_values(_DEFAULT_SOURCES_ENUMS[source]) for source in NativeMarketingSource
}

# Column kind mapping for WebAnalyticsItemBase
COLUMN_KIND_MAPPING = {
    MarketingAnalyticsBaseColumns.ID: "unit",
    MarketingAnalyticsBaseColumns.CAMPAIGN: "unit",
    MarketingAnalyticsBaseColumns.SOURCE: "unit",
    MarketingAnalyticsBaseColumns.COST: "currency",
    MarketingAnalyticsBaseColumns.CLICKS: "unit",
    MarketingAnalyticsBaseColumns.IMPRESSIONS: "unit",
    MarketingAnalyticsBaseColumns.CPC: "currency",
    MarketingAnalyticsBaseColumns.CTR: "percentage",
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION: "unit",
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE: "currency",
    MarketingAnalyticsBaseColumns.REPORTED_ROAS: "unit",
}

# isIncreaseBad mapping for MarketingAnalyticsBaseColumns
IS_INCREASE_BAD_MAPPING = {
    MarketingAnalyticsBaseColumns.ID: False,
    MarketingAnalyticsBaseColumns.CAMPAIGN: False,
    MarketingAnalyticsBaseColumns.SOURCE: False,
    MarketingAnalyticsBaseColumns.COST: True,  # Higher cost is bad
    MarketingAnalyticsBaseColumns.CLICKS: False,  # More clicks is good
    MarketingAnalyticsBaseColumns.IMPRESSIONS: False,  # More impressions is good
    MarketingAnalyticsBaseColumns.CPC: True,  # Higher CPC is bad
    MarketingAnalyticsBaseColumns.CTR: False,  # Higher CTR is good
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION: False,  # More reported conversions is good
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE: False,  # Higher conversion value is good
    MarketingAnalyticsBaseColumns.REPORTED_ROAS: False,  # Higher ROAS is good
}


def to_marketing_analytics_data(
    key: str,
    value: Optional[Union[float, str, list[float], list[str]]],
    previous: Optional[Union[float, str, list[float], list[str]]],
    has_comparison: bool = False,
) -> MarketingAnalyticsItem:
    """
    Transform tuple data to WebAnalyticsItemBase format.
    Similar to web_overview.to_data() but for marketing analytics.
    """
    # Handle list values (from tuple queries)
    if isinstance(value, list):
        value = value[0] if len(value) > 0 else None
    if isinstance(previous, list):
        previous = previous[0] if len(previous) > 0 else None

    # Handle NaN values (only for numeric types)
    if value is not None and isinstance(value, int | float) and math.isnan(value):
        value = None
    if previous is not None and isinstance(previous, int | float) and math.isnan(previous):
        previous = None

    # Determine kind and isIncreaseBad based on column type
    kind = "unit"  # Default
    is_increase_bad = False  # Default

    # Check if it's a base column
    for base_column in MarketingAnalyticsBaseColumns:
        if key == base_column.value:
            kind = COLUMN_KIND_MAPPING.get(base_column, "unit")
            is_increase_bad = IS_INCREASE_BAD_MAPPING.get(base_column, False)
            break
    else:
        # Check if it's a conversion goal or cost per conversion
        if key.startswith(MarketingAnalyticsHelperForColumnNames.COST_PER):
            kind = "currency"
            is_increase_bad = True  # Cost per conversion - higher is bad
        else:
            # Regular conversion goal
            kind = "unit"
            is_increase_bad = False  # More conversions is good

    # For string columns (ID, Campaign, Source), preserve the string values
    if kind == "unit" and key in [
        MarketingAnalyticsBaseColumns.ID.value,
        MarketingAnalyticsBaseColumns.CAMPAIGN.value,
        MarketingAnalyticsBaseColumns.SOURCE.value,
    ]:
        # String columns - no numeric processing needed
        pass
    else:
        # For numeric columns, try to convert strings to numbers
        if isinstance(value, str):
            try:
                value = float(value) if "." in value else int(value)
            except (ValueError, TypeError):
                value = None
        if isinstance(previous, str):
            try:
                previous = float(previous) if "." in previous else int(previous)
            except (ValueError, TypeError):
                previous = None

    # Handle percentage conversion for CTR
    if kind == "percentage":
        # CTR is already calculated as percentage in the query (multiplied by 100)
        # No additional conversion needed
        pass

    # Calculate change percentage (only for numeric values)
    change_from_previous_pct = None
    if (
        value is not None
        and previous is not None
        and isinstance(value, int | float)
        and isinstance(previous, int | float)
    ):
        try:
            if previous == 0:
                # Handle special cases when previous is 0
                if value == 0:
                    # Both are 0: no change
                    change_from_previous_pct = 0
                elif value > 0:
                    # From 0 to positive: use special large number to represent infinite growth
                    change_from_previous_pct = int(InfinityValue.NUMBER_999999)
                else:
                    # From 0 to negative: use special large negative number to represent infinite decrease
                    change_from_previous_pct = int(InfinityValue.NUMBER__999999)
            else:
                # Normal case: previous != 0
                change_from_previous_pct = round(100 * (value - previous) / previous)
        except (ValueError, ZeroDivisionError):
            pass

    return MarketingAnalyticsItem(
        key=key,
        kind=WebAnalyticsItemKind(kind),
        isIncreaseBad=is_increase_bad,
        value=value,
        previous=previous,
        changeFromPreviousPct=change_from_previous_pct,
        hasComparison=has_comparison,
    )
