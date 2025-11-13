from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from posthog.schema import AttributionMode, MarketingAnalyticsBaseColumns, MarketingAnalyticsHelperForColumnNames

if TYPE_CHECKING:
    from posthog.models.team import Team

from .adapters.base import MarketingSourceAdapter
from .constants import (
    CAMPAIGN_COST_CTE_NAME,
    CONVERSION_GOAL_PREFIX,
    CONVERSION_GOAL_PREFIX_ABBREVIATION,
    DECIMAL_PRECISION,
    DEFAULT_DISTINCT_ID_FIELD,
    ORGANIC_CAMPAIGN,
    ORGANIC_SOURCE,
    TOTAL_CLICKS_FIELD,
    TOTAL_COST_FIELD,
    TOTAL_IMPRESSIONS_FIELD,
    TOTAL_REPORTED_CONVERSION_FIELD,
    UNIFIED_CONVERSION_GOALS_CTE_ALIAS,
)


class AttributionModeOperator(Enum):
    LAST_TOUCH = "arrayMax"
    FIRST_TOUCH = "arrayMin"


@dataclass
class MarketingAnalyticsConfig:
    """
    Configuration object that centralizes all constants and naming conventions
    for marketing analytics queries. This makes the system more configurable
    and testable by injecting dependencies rather than hardcoding them.
    """

    # CTE and table names
    campaign_costs_cte_name: str = CAMPAIGN_COST_CTE_NAME
    unified_conversion_goals_cte_alias: str = UNIFIED_CONVERSION_GOALS_CTE_ALIAS

    # Field names for grouping
    campaign_field: str = MarketingSourceAdapter.campaign_name_field
    source_field: str = MarketingSourceAdapter.source_name_field

    # Column aliases for output
    campaign_column_alias: str = MarketingAnalyticsBaseColumns.CAMPAIGN
    source_column_alias: str = MarketingAnalyticsBaseColumns.SOURCE

    # Prefixes for naming
    conversion_goal_prefix: str = CONVERSION_GOAL_PREFIX
    conversion_goal_abbreviation: str = CONVERSION_GOAL_PREFIX_ABBREVIATION
    cost_per_prefix: str = MarketingAnalyticsHelperForColumnNames.COST_PER

    # Default values
    organic_campaign: str = ORGANIC_CAMPAIGN
    organic_source: str = ORGANIC_SOURCE

    # Field references
    total_cost_field: str = TOTAL_COST_FIELD
    total_clicks_field: str = TOTAL_CLICKS_FIELD
    total_impressions_field: str = TOTAL_IMPRESSIONS_FIELD
    total_reported_conversions_field: str = TOTAL_REPORTED_CONVERSION_FIELD
    default_distinct_id_field: str = DEFAULT_DISTINCT_ID_FIELD

    # Precision settings
    decimal_precision: int = DECIMAL_PRECISION

    # Attribution settings (can be overridden by team settings)
    attribution_window_days: int = 90
    attribution_mode: str = AttributionMode.LAST_TOUCH

    @classmethod
    def from_team(cls, team: "Team") -> "MarketingAnalyticsConfig":
        """Create config instance with team-specific attribution settings"""
        config = cls()
        if hasattr(team, "marketing_analytics_config"):
            ma_config = team.marketing_analytics_config
            config.attribution_window_days = ma_config.attribution_window_days
            config.attribution_mode = ma_config.attribution_mode
        return config

    @property
    def attribution_mode_operator(self) -> str:
        """Get the HogQL operator for the attribution mode"""
        if self.attribution_mode == AttributionMode.FIRST_TOUCH:
            return AttributionModeOperator.FIRST_TOUCH.value
        elif self.attribution_mode == AttributionMode.LAST_TOUCH:
            return AttributionModeOperator.LAST_TOUCH.value
        else:
            # Future attribution modes could be added here
            # For now, default to last touch
            return AttributionModeOperator.LAST_TOUCH.value

    @property
    def group_by_fields(self) -> list[str]:
        """Get the list of fields to group by"""
        return [self.campaign_field, self.source_field]

    def get_campaign_cost_field_chain(self, field_name: str) -> list[str | int]:
        """Get field chain for campaign cost CTE fields"""
        return [self.campaign_costs_cte_name, field_name]

    def get_unified_conversion_field_chain(self, field_name: str) -> list[str | int]:
        """Get field chain for unified conversion goals CTE fields"""
        return [self.unified_conversion_goals_cte_alias, field_name]

    def get_conversion_goal_column_name(self, index: int) -> str:
        """Get standardized conversion goal column name"""
        return f"{self.conversion_goal_prefix}{index}"

    def get_conversion_goal_alias(self, index: int) -> str:
        """Get conversion goal CTE alias"""
        return f"{self.conversion_goal_abbreviation}{index}"
