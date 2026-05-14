# Marketing Analytics Constants and Configuration

import math
from typing import Optional, TypedDict, Union

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
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsItem,
    MarketingIntegrationConfig1,
    MarketingIntegrationConfig2,
    MarketingIntegrationConfig3,
    MarketingIntegrationConfig4,
    MarketingIntegrationConfig5,
    MarketingIntegrationConfig6,
    MarketingIntegrationConfig7,
    MarketingIntegrationConfig8,
    MetaAdsConversionFallbackActionTypes,
    MetaAdsConversionOmniActionTypes,
    MetaAdsConversionSpecificActionTypes,
    MetaAdsDefaultSources,
    MetaAdsTableExclusions,
    MetaAdsTableKeywords,
    NativeMarketingSource,
    PinterestAdsDefaultSources,
    PinterestAdsTableExclusions,
    PinterestAdsTableKeywords,
    RedditAdsDefaultSources,
    RedditAdsTableExclusions,
    RedditAdsTableKeywords,
    SnapchatAdsConversionFields,
    SnapchatAdsConversionValueFields,
    SnapchatAdsDefaultSources,
    SnapchatAdsTableExclusions,
    SnapchatAdsTableKeywords,
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

# Placeholder shown in hierarchy columns when an optional parent table isn't synced.
# Example: at AD drill-down with `ads` synced but not `adsets`, the ad_group_name /
# ad_group_id columns surface this label so the user understands why the column is
# blank — instead of showing NULL or an empty string. Adapter-agnostic: any source
# that exposes optional hierarchy tables should reuse this.
UNSYNCED_HIERARCHY_LABEL = "No sync"


# Fallback query when no valid adapters are found. Emits either 9 or 13 columns to
# match the schema adapters produce for the given drill-down level.
def build_fallback_empty_query_ast(
    drill_down_level: MarketingAnalyticsDrillDownLevel | None = None,
) -> ast.SelectQuery:
    select_columns: list[ast.Expr] = [
        ast.Alias(alias=MATCH_KEY_FIELD, expr=ast.Constant(value="")),
        ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.CAMPAIGN, expr=ast.Constant(value="No Campaign")),
        ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.ID, expr=ast.Constant(value="No ID")),
        ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.SOURCE, expr=ast.Constant(value="No Source")),
    ]
    if drill_down_level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
        # Match the 13-column schema adapters emit at ad-group / ad levels so the UNION
        # stays consistent when no adapter supports this level.
        select_columns.extend(
            [
                ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.AD_GROUP_NAME, expr=ast.Constant(value=None)),
                ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.AD_GROUP_ID, expr=ast.Constant(value=None)),
                ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.AD_NAME, expr=ast.Constant(value=None)),
                ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.AD_ID, expr=ast.Constant(value=None)),
            ]
        )
    select_columns.extend(
        [
            ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS, expr=ast.Constant(value=0.0)),
            ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.CLICKS, expr=ast.Constant(value=0.0)),
            ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.COST, expr=ast.Constant(value=0.0)),
            ast.Alias(alias=MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION, expr=ast.Constant(value=0.0)),
            ast.Alias(
                alias=MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION_VALUE, expr=ast.Constant(value=0.0)
            ),
        ]
    )
    return ast.SelectQuery(
        select=select_columns,
        where=ast.CompareOperation(
            left=ast.Constant(value=1),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=0),
        ),
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
    # Naming inconsistency: the schema name uses `_name` suffixes (`ad_group_name`,
    # `ad_name`) while CAMPAIGN's schema name is just `campaign`. Predates this PR;
    # changing the older convention would require a migration of saved source_map
    # configs across all teams. The display alias ("Ad group" / "Ad") hides the
    # inconsistency from the UI.
    MarketingAnalyticsBaseColumns.AD_GROUP: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.AD_GROUP,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.AD_GROUP_NAME]),
    ),
    MarketingAnalyticsBaseColumns.AD_GROUP_ID: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.AD_GROUP_ID,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.AD_GROUP_ID]),
    ),
    MarketingAnalyticsBaseColumns.AD: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.AD,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.AD_NAME]),
    ),
    MarketingAnalyticsBaseColumns.AD_ID: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.AD_ID,
        expr=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, MarketingAnalyticsColumnsSchemaNames.AD_ID]),
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
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSIONS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.REPORTED_CONVERSIONS,
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
    MarketingAnalyticsBaseColumns.COST_PER_REPORTED_CONVERSIONS: ast.Alias(
        alias=MarketingAnalyticsBaseColumns.COST_PER_REPORTED_CONVERSIONS,
        expr=ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_COST_FIELD]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(
                        name="nullif",
                        args=[
                            ast.Field(chain=[CAMPAIGN_COST_CTE_NAME, TOTAL_REPORTED_CONVERSION_FIELD]),
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

# Hierarchy columns are emitted by the campaign_costs CTE only at AD_GROUP / AD levels
# (the adapters add ad_group_name / ad_group_id / ad_name / ad_id to their SELECT only
# at those levels — see MarketingSourceAdapter._build_select_columns). At every other
# level the CTE schema doesn't have them, so the runtime adds these to the excluded
# set automatically. Keeping this in one place means level configs don't need to repeat
# the four entries, and adding a new hierarchy column only requires updating this set
# plus the adapter SELECT.
HIERARCHY_BASE_COLUMNS: frozenset[MarketingAnalyticsBaseColumns] = frozenset(
    {
        MarketingAnalyticsBaseColumns.AD_GROUP,
        MarketingAnalyticsBaseColumns.AD_GROUP_ID,
        MarketingAnalyticsBaseColumns.AD,
        MarketingAnalyticsBaseColumns.AD_ID,
    }
)

# Levels that emit hierarchy columns from the CTE. Other levels exclude them automatically
# via HIERARCHY_BASE_COLUMNS.
HIERARCHY_DRILL_DOWN_LEVELS: frozenset[MarketingAnalyticsDrillDownLevel] = frozenset(
    {MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD}
)


def get_effective_excluded_columns(
    level: MarketingAnalyticsDrillDownLevel,
) -> frozenset[MarketingAnalyticsBaseColumns]:
    """Combine the level's user-facing excluded set with the hierarchy auto-exclusion.
    Returns the full set of columns the runtime should not emit at this level."""
    user_excluded = DRILL_DOWN_LEVEL_CONFIG[level]["excluded_base_columns"]
    if level in HIERARCHY_DRILL_DOWN_LEVELS:
        return user_excluded
    return user_excluded | HIERARCHY_BASE_COLUMNS


class DrillDownLevelConfig(TypedDict, total=False):
    column_alias: str
    excluded_base_columns: frozenset[MarketingAnalyticsBaseColumns]
    # When True, this level can't be attributed to events — conversion goal columns
    # are dropped. Used for ad-group / ad levels where the platform supplies cost data
    # but events can't be mapped to a specific ad.
    excludes_conversion_goals: bool


# Centralized drill-down level configuration. Hierarchy columns (ad_group / ad) are
# auto-excluded by the runtime at non-hierarchy levels — see HIERARCHY_BASE_COLUMNS —
# so they don't need to appear in `excluded_base_columns` for CHANNEL/SOURCE/CAMPAIGN/UTM.
DRILL_DOWN_LEVEL_CONFIG: dict[MarketingAnalyticsDrillDownLevel, DrillDownLevelConfig] = {
    MarketingAnalyticsDrillDownLevel.CHANNEL: {
        "column_alias": "Channel",
        "excluded_base_columns": frozenset(
            {
                MarketingAnalyticsBaseColumns.ID,
                MarketingAnalyticsBaseColumns.CAMPAIGN,
                MarketingAnalyticsBaseColumns.SOURCE,
            }
        ),
    },
    MarketingAnalyticsDrillDownLevel.SOURCE: {
        "column_alias": MarketingAnalyticsBaseColumns.SOURCE,
        "excluded_base_columns": frozenset(
            {
                MarketingAnalyticsBaseColumns.ID,
                MarketingAnalyticsBaseColumns.CAMPAIGN,
                MarketingAnalyticsBaseColumns.SOURCE,
            }
        ),
    },
    MarketingAnalyticsDrillDownLevel.CAMPAIGN: {
        "column_alias": MarketingAnalyticsBaseColumns.CAMPAIGN,
        # Empty user-config preserves master's natural enum order at CAMPAIGN —
        # hierarchy columns are auto-excluded by the runtime.
        "excluded_base_columns": frozenset(),
    },
    MarketingAnalyticsDrillDownLevel.AD_GROUP: {
        # Show parent context (Campaign + Source) plus the ad-group itself.
        # Hide campaign Id and ad-level columns (they don't apply at this level).
        "column_alias": MarketingAnalyticsBaseColumns.AD_GROUP,
        "excluded_base_columns": frozenset(
            {
                MarketingAnalyticsBaseColumns.ID,
                MarketingAnalyticsBaseColumns.AD,
                MarketingAnalyticsBaseColumns.AD_ID,
            }
        ),
        "excludes_conversion_goals": True,
    },
    MarketingAnalyticsDrillDownLevel.AD: {
        # Full hierarchy: Campaign + Source + Ad group + Ad. Hide campaign Id and ad-group ID.
        "column_alias": MarketingAnalyticsBaseColumns.AD,
        "excluded_base_columns": frozenset(
            {
                MarketingAnalyticsBaseColumns.ID,
                MarketingAnalyticsBaseColumns.AD_GROUP_ID,
            }
        ),
        "excludes_conversion_goals": True,
    },
    # UTM levels: platform cost can't be attributed to a UTM value, so all base columns
    # are stripped — only the grouping alias + conversion goal columns remain. The
    # runtime hierarchy auto-exclusion is a no-op here (already in `frozenset(...)`).
    MarketingAnalyticsDrillDownLevel.MEDIUM: {
        "column_alias": "Medium",
        "excluded_base_columns": frozenset(MarketingAnalyticsBaseColumns),
    },
    MarketingAnalyticsDrillDownLevel.CONTENT: {
        "column_alias": "Content",
        "excluded_base_columns": frozenset(MarketingAnalyticsBaseColumns),
    },
    MarketingAnalyticsDrillDownLevel.TERM: {
        "column_alias": "Term",
        "excluded_base_columns": frozenset(MarketingAnalyticsBaseColumns),
    },
}

# All possible grouping column aliases (used to identify string columns)
DRILL_DOWN_STRING_COLUMN_ALIASES: frozenset[str] = frozenset(
    cfg["column_alias"] for cfg in DRILL_DOWN_LEVEL_CONFIG.values()
)

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
    # Ad group / ad fields — optional. Only platforms that expose ad-group / ad
    # granularity (Meta, Google Ads, TikTok, Reddit, Pinterest, Snapchat, Bing) will
    # populate these. When absent, the corresponding drill-down levels show no data
    # for that source.
    MarketingAnalyticsColumnsSchemaNames.AD_GROUP_ID: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.AD_GROUP_NAME: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.AD_ID: {"required": False},
    MarketingAnalyticsColumnsSchemaNames.AD_NAME: {"required": False},
}

# Valid native marketing sources - derived from generated enum
VALID_NATIVE_MARKETING_SOURCES = [source.value for source in NativeMarketingSource]

# Valid non-native marketing sources (managed external sources like BigQuery)
VALID_NON_NATIVE_MARKETING_SOURCES = ["BigQuery"]

# Valid self-managed marketing sources (mirrors frontend types)
VALID_SELF_MANAGED_MARKETING_SOURCES = ["aws", "google-cloud", "cloudflare-r2", "azure"]

# Map generated config models to NativeMarketingSource using sourceType field
_ALL_CONFIG_MODELS: list[type[BaseModel]] = [
    MarketingIntegrationConfig1,
    MarketingIntegrationConfig2,
    MarketingIntegrationConfig3,
    MarketingIntegrationConfig4,
    MarketingIntegrationConfig5,
    MarketingIntegrationConfig6,
    MarketingIntegrationConfig7,
    MarketingIntegrationConfig8,
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
    NativeMarketingSource.SNAPCHAT_ADS: SnapchatAdsDefaultSources,
    NativeMarketingSource.PINTEREST_ADS: PinterestAdsDefaultSources,
}

_TABLE_KEYWORDS_ENUMS = {
    NativeMarketingSource.GOOGLE_ADS: GoogleAdsTableKeywords,
    NativeMarketingSource.LINKEDIN_ADS: LinkedinAdsTableKeywords,
    NativeMarketingSource.META_ADS: MetaAdsTableKeywords,
    NativeMarketingSource.TIK_TOK_ADS: TikTokAdsTableKeywords,
    NativeMarketingSource.REDDIT_ADS: RedditAdsTableKeywords,
    NativeMarketingSource.BING_ADS: BingAdsTableKeywords,
    NativeMarketingSource.SNAPCHAT_ADS: SnapchatAdsTableKeywords,
    NativeMarketingSource.PINTEREST_ADS: PinterestAdsTableKeywords,
}

_TABLE_EXCLUSIONS_ENUMS = {
    NativeMarketingSource.GOOGLE_ADS: GoogleAdsTableExclusions,
    NativeMarketingSource.LINKEDIN_ADS: LinkedinAdsTableExclusions,
    NativeMarketingSource.META_ADS: MetaAdsTableExclusions,
    NativeMarketingSource.TIK_TOK_ADS: TikTokAdsTableExclusions,
    NativeMarketingSource.REDDIT_ADS: RedditAdsTableExclusions,
    NativeMarketingSource.BING_ADS: BingAdsTableExclusions,
    NativeMarketingSource.SNAPCHAT_ADS: SnapchatAdsTableExclusions,
    NativeMarketingSource.PINTEREST_ADS: PinterestAdsTableExclusions,
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

# Snapchat Ads conversion fields - derived from generated enums
SNAPCHAT_CONVERSION_FIELDS = [e.value for e in SnapchatAdsConversionFields]
SNAPCHAT_CONVERSION_VALUE_FIELDS = [e.value for e in SnapchatAdsConversionValueFields]

# Meta Ads conversion action types - derived from generated enums
META_CONVERSION_ACTION_TYPES = {
    "omni": [e.value for e in MetaAdsConversionOmniActionTypes],
    "fallback": [e.value for e in MetaAdsConversionFallbackActionTypes],
    "specific": [e.value for e in MetaAdsConversionSpecificActionTypes],
}

# Column kind mapping for WebAnalyticsItemBase
COLUMN_KIND_MAPPING = {
    MarketingAnalyticsBaseColumns.ID: "unit",
    MarketingAnalyticsBaseColumns.CAMPAIGN: "unit",
    MarketingAnalyticsBaseColumns.SOURCE: "unit",
    MarketingAnalyticsBaseColumns.AD_GROUP: "unit",
    MarketingAnalyticsBaseColumns.AD_GROUP_ID: "unit",
    MarketingAnalyticsBaseColumns.AD: "unit",
    MarketingAnalyticsBaseColumns.AD_ID: "unit",
    MarketingAnalyticsBaseColumns.COST: "currency",
    MarketingAnalyticsBaseColumns.CLICKS: "unit",
    MarketingAnalyticsBaseColumns.IMPRESSIONS: "unit",
    MarketingAnalyticsBaseColumns.CPC: "currency",
    MarketingAnalyticsBaseColumns.CTR: "percentage",
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSIONS: "unit",
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE: "currency",
    MarketingAnalyticsBaseColumns.REPORTED_ROAS: "unit",
    MarketingAnalyticsBaseColumns.COST_PER_REPORTED_CONVERSIONS: "currency",
}

# isIncreaseBad mapping for MarketingAnalyticsBaseColumns
IS_INCREASE_BAD_MAPPING = {
    MarketingAnalyticsBaseColumns.ID: False,
    MarketingAnalyticsBaseColumns.CAMPAIGN: False,
    MarketingAnalyticsBaseColumns.SOURCE: False,
    MarketingAnalyticsBaseColumns.AD_GROUP: False,
    MarketingAnalyticsBaseColumns.AD_GROUP_ID: False,
    MarketingAnalyticsBaseColumns.AD: False,
    MarketingAnalyticsBaseColumns.AD_ID: False,
    MarketingAnalyticsBaseColumns.COST: True,  # Higher cost is bad
    MarketingAnalyticsBaseColumns.CLICKS: False,  # More clicks is good
    MarketingAnalyticsBaseColumns.IMPRESSIONS: False,  # More impressions is good
    MarketingAnalyticsBaseColumns.CPC: True,  # Higher CPC is bad
    MarketingAnalyticsBaseColumns.CTR: False,  # Higher CTR is good
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSIONS: False,  # More reported conversions is good
    MarketingAnalyticsBaseColumns.REPORTED_CONVERSION_VALUE: False,  # Higher conversion value is good
    MarketingAnalyticsBaseColumns.REPORTED_ROAS: False,  # Higher ROAS is good
    MarketingAnalyticsBaseColumns.COST_PER_REPORTED_CONVERSIONS: True,  # Higher cost per conversion is bad
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
        if key.startswith(MarketingAnalyticsConstants.COST_PER):
            kind = "currency"
            is_increase_bad = True  # Cost per conversion - higher is bad
        else:
            # Regular conversion goal
            kind = "unit"
            is_increase_bad = False  # More conversions is good

    # For string columns (IDs, names, and drill-down grouping aliases), preserve the string
    # values. ID columns hold platform identifiers (Meta ad IDs are 17-digit numbers) and
    # must NOT be coerced to int — the frontend formats numbers in compact form ("120000T").
    string_columns = DRILL_DOWN_STRING_COLUMN_ALIASES | {
        MarketingAnalyticsBaseColumns.ID.value,
        MarketingAnalyticsBaseColumns.AD_GROUP_ID.value,
        MarketingAnalyticsBaseColumns.AD_ID.value,
    }
    if kind == "unit" and key in string_columns:
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
