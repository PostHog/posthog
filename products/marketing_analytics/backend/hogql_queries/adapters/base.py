# Base Marketing Source Adapter

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

import structlog

from posthog.schema import (
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    SourceMap,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

from products.data_warehouse.backend.models import DataWarehouseTable
from products.marketing_analytics.backend.hogql_queries.constants import DRILL_DOWN_LEVEL_CONFIG, MATCH_KEY_FIELD

logger = structlog.get_logger(__name__)

ConfigType = TypeVar("ConfigType", bound="BaseMarketingConfig")


@dataclass
class BaseMarketingConfig(ABC):
    """Base configuration for marketing source adapters"""

    source_type: str
    source_id: str


@dataclass
class ExternalConfig(BaseMarketingConfig):
    """Configuration for external marketing sources"""

    table: DataWarehouseTable
    source_map: SourceMap
    schema_name: str


@dataclass
class GoogleAdsConfig(BaseMarketingConfig):
    """Configuration for Google Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class LinkedinAdsConfig(BaseMarketingConfig):
    """Configuration for LinkedIn Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class RedditAdsConfig(BaseMarketingConfig):
    """Configuration for Reddit Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class MetaAdsConfig(BaseMarketingConfig):
    """Configuration for Meta Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable
    # Ad-group (adset) and ad tables are optional — only present when the user has
    # those schemas marked for sync in their data warehouse.
    adset_table: Optional[DataWarehouseTable] = None
    adset_stats_table: Optional[DataWarehouseTable] = None
    ad_table: Optional[DataWarehouseTable] = None
    ad_stats_table: Optional[DataWarehouseTable] = None


@dataclass
class TikTokAdsConfig(BaseMarketingConfig):
    """Configuration for TikTok Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class BingAdsConfig(BaseMarketingConfig):
    """Configuration for Bing Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class SnapchatAdsConfig(BaseMarketingConfig):
    """Configuration for Snapchat Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class PinterestAdsConfig(BaseMarketingConfig):
    """Configuration for Pinterest Ads marketing sources"""

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable


@dataclass
class ValidationResult:
    """Result of source validation"""

    is_valid: bool
    errors: list[str]


@dataclass
class QueryContext:
    """Context needed for query building"""

    date_range: Optional[QueryDateRange]
    team: Team
    global_filters: list[Any] = field(default_factory=list)
    base_currency: str = DEFAULT_CURRENCY
    # Drill-down level controls which platform tables the adapter pulls from.
    # CAMPAIGN (default) and below query campaign-level stats. AD_GROUP / AD switch
    # to ad-group / ad-level tables when the adapter supports them.
    drill_down_level: MarketingAnalyticsDrillDownLevel = MarketingAnalyticsDrillDownLevel.CAMPAIGN


class MarketingSourceAdapter(ABC, Generic[ConfigType]):
    """
    Base adapter that all marketing sources must implement.
    Each adapter is responsible for:
    1. Validating that it can provide marketing data
    2. Building a SQL query fragment that returns standardized marketing data
    """

    # Default fields for the marketing analytics table
    campaign_name_field: str = MarketingAnalyticsColumnsSchemaNames.CAMPAIGN
    campaign_id_field: str = MarketingAnalyticsColumnsSchemaNames.ID
    source_name_field: str = MarketingAnalyticsColumnsSchemaNames.SOURCE
    impressions_field: str = MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS
    clicks_field: str = MarketingAnalyticsColumnsSchemaNames.CLICKS
    cost_field: str = MarketingAnalyticsColumnsSchemaNames.COST
    reported_conversion_field: str = MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION
    reported_conversion_value_field: str = MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION_VALUE
    # Ad-group / ad granularity. Emitted by every adapter (NULL when the source doesn't
    # support that granularity or the query isn't at that drill-down level) so the
    # campaign_costs CTE has a stable schema.
    ad_group_name_field: str = MarketingAnalyticsColumnsSchemaNames.AD_GROUP_NAME
    ad_group_id_field: str = MarketingAnalyticsColumnsSchemaNames.AD_GROUP_ID
    ad_name_field: str = MarketingAnalyticsColumnsSchemaNames.AD_NAME
    ad_id_field: str = MarketingAnalyticsColumnsSchemaNames.AD_ID
    match_key_field: str = MATCH_KEY_FIELD

    CONSTANT_VALUE_PREFIX = MarketingAnalyticsConstants.CONST_

    @staticmethod
    def _is_simple_column_name(value: str) -> bool:
        # Handle single character case first
        if len(value) == 1:
            return value.isalnum() or value == "_"
        return (
            bool(value)
            and value.replace("_", "").replace(".", "").isalnum()
            and not value.startswith(".")
            and not value.endswith(".")
        )

    def _resolve_field_expr(self, field_value: str) -> ast.Expr:
        if self._is_simple_column_name(field_value):
            parts: list[str | int] = list(field_value.split("."))
            return ast.Field(chain=parts)
        return parse_expr(field_value)

    # Matches bare ISO 4217 currency codes like "USD", "EUR", "GBP"
    _ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

    def _resolve_field_or_constant(self, field_value: str) -> ast.Expr:
        """Resolve a field value that may be a column reference or a constant.
        Values prefixed with 'const:' are treated as string constants.
        For backwards compatibility, bare ISO currency codes (e.g. "USD")
        saved before the frontend enforced the 'const:' prefix are also
        treated as constants.
        """
        if field_value.startswith(self.CONSTANT_VALUE_PREFIX):
            return ast.Constant(value=field_value[len(self.CONSTANT_VALUE_PREFIX) :])
        if self._ISO_CURRENCY_RE.match(field_value):
            return ast.Constant(value=field_value)
        return self._resolve_field_expr(field_value)

    @classmethod
    @abstractmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """
        Return a mapping of primary source identifier to all possible UTM source values.
        Used to normalize conversion goal sources to match campaign costs.

        Example:
            return {"google": ["google", "youtube", "search", "display", ...]}

        For single-source adapters, return a mapping with just the primary source:
            return {"meta": ["meta"]}
        """
        pass

    def __init__(self, config: ConfigType, context: QueryContext):
        self.team = context.team
        self.config: ConfigType = config
        self.logger = logger.bind(source_type=self.get_source_type(), team_id=self.team.pk if self.team else None)
        self.context = context
        # Cache for `_table_has_column` lookups. Keyed by (id(table), column_name) so we
        # don't re-introspect the warehouse table on each currency-conversion call (at AD
        # level the same stats table is hit 3 times per query for cost / conversions /
        # conversion_value).
        self._table_column_cache: dict[tuple[int, str], bool] = {}

    @abstractmethod
    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        pass

    def get_source_id(self) -> str:
        """Return the source ID for filtering purposes"""
        return self.config.source_id

    @abstractmethod
    def validate(self) -> ValidationResult:
        """
        Validate that this source can provide marketing data.
        Should check:
        - Required tables/fields exist
        - Proper permissions/credentials
        - Data availability
        """
        pass

    @abstractmethod
    def _get_campaign_name_field(self) -> ast.Expr:
        """Get the campaign name field expression"""

        pass

    @abstractmethod
    def _get_campaign_id_field(self) -> ast.Expr:
        """Get the campaign ID field expression"""
        pass

    def _get_source_name_field(self) -> ast.Expr:
        """
        Get the source name field expression (returns the primary source identifier).
        Default implementation returns the key from get_source_identifier_mapping().
        For example, {"reddit": ["reddit", "red"]} returns "reddit".
        Override if you need custom logic (e.g., user-configured sources).
        """
        mapping = self.get_source_identifier_mapping()
        if not mapping:
            raise NotImplementedError(
                f"{self.__class__.__name__} has no source identifier mapping. "
                "Either provide a mapping or override _get_source_name_field()."
            )
        assert len(mapping) > 0, "Should have at least one source identifier mapping"
        primary_source = next(iter(mapping.keys()))
        return ast.Call(name="toString", args=[ast.Constant(value=primary_source)])

    @abstractmethod
    def _get_impressions_field(self) -> ast.Expr:
        """Get the impressions field expression"""
        pass

    @abstractmethod
    def _get_clicks_field(self) -> ast.Expr:
        """Get the clicks field expression"""
        pass

    @abstractmethod
    def _get_cost_field(self) -> ast.Expr:
        """Get the cost field expression"""
        pass

    @abstractmethod
    def _get_reported_conversion_field(self) -> ast.Expr:
        """Get the reported conversion count field expression"""
        pass

    @abstractmethod
    def _get_reported_conversion_value_field(self) -> ast.Expr:
        """Get the reported conversion value (monetary) field expression"""
        pass

    def _get_ad_group_name_field(self) -> ast.Expr:
        """Get the ad group name field expression. Default NULL — adapters that support
        ad-group granularity override this when the query is at AD_GROUP or AD level."""
        return ast.Constant(value=None)

    def _get_ad_group_id_field(self) -> ast.Expr:
        """Get the ad group ID field expression. Default NULL."""
        return ast.Constant(value=None)

    def _get_ad_name_field(self) -> ast.Expr:
        """Get the ad name field expression. Default NULL — adapters that support
        ad granularity override this when the query is at AD level."""
        return ast.Constant(value=None)

    def _get_ad_id_field(self) -> ast.Expr:
        """Get the ad ID field expression. Default NULL."""
        return ast.Constant(value=None)

    def _string_field_when_level(
        self,
        levels: tuple[MarketingAnalyticsDrillDownLevel, ...],
        table: Optional[DataWarehouseTable],
        column: str,
    ) -> ast.Expr:
        """Helper for adapters implementing hierarchy fields. Returns
        toString(table.column) when the current drill-down level is in `levels`
        and the table is configured; otherwise NULL.

        Used to keep `_get_ad_group_*_field` / `_get_ad_*_field` overrides one-liners
        across the 8 adapter implementations (Meta done, others to follow).
        """
        if table is not None and self.context.drill_down_level in levels:
            return ast.Call(name="toString", args=[ast.Field(chain=[table.name, column])])
        return ast.Constant(value=None)

    def supports_level(self, level: MarketingAnalyticsDrillDownLevel) -> bool:
        """Whether this adapter can return data for the given drill-down level.
        Default: supports campaign-level and below (channel, source, campaign, utm levels).
        Override in adapters that implement AD_GROUP / AD level tables."""
        return level not in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD)

    @abstractmethod
    def _get_where_conditions(self) -> list[ast.Expr]:
        """Get WHERE condition expressions"""
        pass

    @abstractmethod
    def _get_from(self) -> ast.JoinExpr:
        """Get the FROM clause"""
        pass

    @abstractmethod
    def _get_group_by(self) -> list[ast.Expr]:
        """Get GROUP BY expressions"""
        pass

    def _get_campaign_field_preference(self) -> str:
        """
        Get campaign field matching preference for this integration from team config.

        Returns: "campaign_name" or "campaign_id"

        Defaults to campaign_name if no preference set (backward compatible).
        """
        try:
            preferences = self.team.marketing_analytics_config.campaign_field_preferences
            integration_prefs = preferences.get(self.get_source_type(), {})
            return integration_prefs.get("match_field", "campaign_name")
        except Exception:
            # If any error accessing config, default to campaign_name
            return "campaign_name"

    def get_campaign_match_field(self) -> ast.Expr:
        """
        Get the campaign field expression to use for matching with utm_campaign.
        This respects the campaign_field_preferences setting.

        Returns either campaign_name or campaign_id field based on configuration.
        """
        preference = self._get_campaign_field_preference()
        if preference == "campaign_id":
            return self._get_campaign_id_field()
        return self._get_campaign_name_field()

    def _get_match_key_expr(self) -> ast.Expr:
        """Expression emitted as the `match_key` column. The runner JOINs adapter output
        against unified_conversion_goals on this column — but at levels where that JOIN
        is skipped (currently AD_GROUP / AD; gated by `excludes_conversion_goals`), the
        match value is unused and emitting `campaign_name` is just a confusing duplicate
        of the campaign column. Empty constant communicates intent and saves wire bytes.

        Tied to DRILL_DOWN_LEVEL_CONFIG so any future level that flips
        `excludes_conversion_goals` automatically inherits this behavior.
        """
        level_config = DRILL_DOWN_LEVEL_CONFIG.get(self.context.drill_down_level)
        if level_config and level_config.get("excludes_conversion_goals"):
            return ast.Constant(value="")
        return self.get_campaign_match_field()

    def _table_has_column(self, table: DataWarehouseTable, column_name: str) -> bool:
        """Cached column-existence check for warehouse tables. Used by hot paths like
        `_apply_currency_conversion` and `_build_actions_conversion_sum` (Meta) that
        call into the same table multiple times per query."""
        cache_key = (id(table), column_name)
        cached = self._table_column_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            columns = getattr(table, "columns", None)
            present = bool(columns and hasattr(columns, "__contains__") and column_name in columns)
        except (TypeError, AttributeError, KeyError):
            present = False
        self._table_column_cache[cache_key] = present
        return present

    def _apply_currency_conversion(
        self,
        table: DataWarehouseTable,
        table_name: str,
        currency_column: str,
        value_expr: ast.Expr,
    ) -> ast.Expr | None:
        """Wrap value_expr with currency conversion if the currency column exists in the table.

        Returns toFloat(convertCurrency(coalesce(currency_col, base_currency), base_currency, value_expr))
        or None if the column doesn't exist or can't be checked.
        """
        if not self._table_has_column(table, currency_column):
            return None
        currency_field = ast.Field(chain=[table_name, currency_column])
        currency_with_fallback = ast.Call(
            name="coalesce", args=[currency_field, ast.Constant(value=self.context.base_currency)]
        )
        converted = ast.Call(
            name="convertCurrency",
            args=[currency_with_fallback, ast.Constant(value=self.context.base_currency), value_expr],
        )
        return ast.Call(name="toFloat", args=[converted])

    def _log_validation_errors(self, errors: list[str]):
        """Helper to log validation issues"""
        if errors:
            self.logger.error("Source validation failed", errors=errors)

    def _log_query_generation(self, success: bool, error: str | None = None):
        """Helper to log query generation status"""
        if success:
            self.logger.debug("Query generated successfully")
        else:
            self.logger.error("Query generation failed", error=error)

    def _build_select_columns(self) -> list[ast.Expr]:
        """Build the standardized SELECT columns for marketing analytics queries.
        match_key first (stable position for joins), then data columns.

        The ad_group / ad columns are only emitted at AD_GROUP / AD drill-down levels —
        at other levels the 9-column schema is preserved for backward compatibility.
        """
        columns: list[ast.Expr] = [
            ast.Alias(alias=self.match_key_field, expr=self._get_match_key_expr()),
            ast.Alias(alias=self.campaign_name_field, expr=self._get_campaign_name_field()),
            ast.Alias(alias=self.campaign_id_field, expr=self._get_campaign_id_field()),
            ast.Alias(alias=self.source_name_field, expr=self._get_source_name_field()),
        ]
        if self.context.drill_down_level in (
            MarketingAnalyticsDrillDownLevel.AD_GROUP,
            MarketingAnalyticsDrillDownLevel.AD,
        ):
            columns.extend(
                [
                    ast.Alias(alias=self.ad_group_name_field, expr=self._get_ad_group_name_field()),
                    ast.Alias(alias=self.ad_group_id_field, expr=self._get_ad_group_id_field()),
                    ast.Alias(alias=self.ad_name_field, expr=self._get_ad_name_field()),
                    ast.Alias(alias=self.ad_id_field, expr=self._get_ad_id_field()),
                ]
            )
        columns.extend(
            [
                ast.Alias(alias=self.impressions_field, expr=self._get_impressions_field()),
                ast.Alias(alias=self.clicks_field, expr=self._get_clicks_field()),
                ast.Alias(alias=self.cost_field, expr=self._get_cost_field()),
                ast.Alias(alias=self.reported_conversion_field, expr=self._get_reported_conversion_field()),
                ast.Alias(alias=self.reported_conversion_value_field, expr=self._get_reported_conversion_value_field()),
            ]
        )
        return columns

    def build_query(self) -> Optional[ast.SelectQuery]:
        """
        Build SelectQuery that returns marketing data in standardized format.

        Column count varies by drill-down level (the campaign_costs CTE consumer expects
        the same shape from every adapter at a given level):

        - At CHANNEL / SOURCE / CAMPAIGN / MEDIUM / CONTENT / TERM: 9 columns
        - At AD_GROUP / AD: 13 columns (ad_group_name/id + ad_name/id inserted after
          source_name)

        Column order at AD_GROUP / AD:
        - match_key (string): Campaign match field for joining with conversion goals
        - campaign_name (string): Campaign identifier (human-readable name)
        - campaign_id (string): Campaign identifier (platform ID)
        - source_name (string): Source identifier
        - ad_group_name (string | null): Ad group name (null when source doesn't support it)
        - ad_group_id (string | null): Ad group platform ID
        - ad_name (string | null): Ad name (null at AD_GROUP level or unsupported)
        - ad_id (string | null): Ad platform ID
        - impressions (float): Number of impressions
        - clicks (float): Number of clicks
        - cost (float): Total cost in base currency
        - reported_conversion (float): Number of reported conversions
        - reported_conversion_value (float): Monetary value of reported conversions

        Returns None if this source cannot provide data for the given context.
        """
        try:
            select_columns = self._build_select_columns()

            # Build query components
            from_expr = self._get_from()
            where_conditions = self._get_where_conditions()
            group_by_exprs = self._get_group_by()

            # Build WHERE clause
            where_expr = None
            if where_conditions:
                if len(where_conditions) == 1:
                    where_expr = where_conditions[0]
                else:
                    where_expr = ast.And(exprs=where_conditions)

            # Build GROUP BY clause
            group_by = group_by_exprs if group_by_exprs else None

            # Create the complete SelectQuery
            query = ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr, group_by=group_by)

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self.logger.error("Query generation failed", error=error_msg, exc_info=True)
            self._log_query_generation(False, error_msg)
            return None
