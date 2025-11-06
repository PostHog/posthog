# Base Marketing Source Adapter

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

import structlog

from posthog.schema import MarketingAnalyticsColumnsSchemaNames, SourceMap

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

from products.data_warehouse.backend.models import DataWarehouseTable

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


@dataclass
class TikTokAdsConfig(BaseMarketingConfig):
    """Configuration for TikTok Ads marketing sources"""

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

    date_range: QueryDateRange
    team: Team
    global_filters: list[Any] = field(default_factory=list)
    base_currency: str = DEFAULT_CURRENCY


class MarketingSourceAdapter(ABC, Generic[ConfigType]):
    """
    Base adapter that all marketing sources must implement.
    Each adapter is responsible for:
    1. Validating that it can provide marketing data
    2. Building a SQL query fragment that returns standardized marketing data
    """

    # Default fields for the marketing analytics table
    campaign_name_field: str = MarketingAnalyticsColumnsSchemaNames.CAMPAIGN
    source_name_field: str = MarketingAnalyticsColumnsSchemaNames.SOURCE
    impressions_field: str = MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS
    clicks_field: str = MarketingAnalyticsColumnsSchemaNames.CLICKS
    cost_field: str = MarketingAnalyticsColumnsSchemaNames.COST
    reported_conversion_field: str = MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION

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
        """Get the reported conversion field expression"""
        pass

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

    def build_query(self) -> Optional[ast.SelectQuery]:
        """
        Build SelectQuery that returns marketing data in standardized format.

        MUST return columns in this exact order and format:
        - campaign_name (string): Campaign identifier
        - source_name (string): Source identifier
        - impressions (float): Number of impressions
        - clicks (float): Number of clicks
        - cost (float): Total cost in base currency

        Returns None if this source cannot provide data for the given context.
        """
        try:
            # Build SELECT columns
            select_columns: list[ast.Expr] = [
                ast.Alias(alias=self.campaign_name_field, expr=self._get_campaign_name_field()),
                ast.Alias(alias=self.source_name_field, expr=self._get_source_name_field()),
                ast.Alias(alias=self.impressions_field, expr=self._get_impressions_field()),
                ast.Alias(alias=self.clicks_field, expr=self._get_clicks_field()),
                ast.Alias(alias=self.cost_field, expr=self._get_cost_field()),
                ast.Alias(alias=self.reported_conversion_field, expr=self._get_reported_conversion_field()),
            ]

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

    def build_query_string(self) -> Optional[str]:
        """
        Build SQL query string (backwards compatibility).
        """
        query = self.build_query()
        return query.to_hogql() if query else None
