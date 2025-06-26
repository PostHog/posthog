# Base Marketing Source Adapter

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
import structlog

from posthog.models.team.team import DEFAULT_CURRENCY
from products.marketing_analytics.backend.hogql_queries.constants import (
    CAMPAIGN_NAME_FIELD,
    CLICKS_FIELD,
    COST_FIELD,
    IMPRESSIONS_FIELD,
    SOURCE_NAME_FIELD,
)

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of source validation"""

    is_valid: bool
    errors: list[str]
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class QueryContext:
    """Context needed for query building"""

    date_range: Any  # QueryDateRange
    team: Any
    global_filters: list[Any] = None
    base_currency: str = DEFAULT_CURRENCY

    def __post_init__(self):
        if self.global_filters is None:
            self.global_filters = []


class MarketingSourceAdapter(ABC):
    """
    Base adapter that all marketing sources must implement.
    Each adapter is responsible for:
    1. Validating that it can provide marketing data
    2. Building a SQL query fragment that returns standardized marketing data
    """

    # Default fields for the marketing analytics table
    campaign_name_field: str = CAMPAIGN_NAME_FIELD
    source_name_field: str = SOURCE_NAME_FIELD
    impressions_field: str = IMPRESSIONS_FIELD
    clicks_field: str = CLICKS_FIELD
    cost_field: str = COST_FIELD

    def __init__(self, config: dict[str, Any], context: QueryContext):
        self.team = context.team
        self.config = config
        self.logger = logger.bind(source_type=self.get_source_type(), team_id=self.team.pk if self.team else None)
        self.context = context

    @abstractmethod
    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        pass

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
    def _get_campaign_name_field(self) -> str:
        """Get the campaign name field for the query"""
        pass

    @abstractmethod
    def _get_source_name_field(self) -> str:
        """Get the source name field for the query"""
        pass

    @abstractmethod
    def _get_impressions_field(self) -> str:
        """Get the impressions field for the query"""
        pass

    @abstractmethod
    def _get_clicks_field(self) -> str:
        """Get the clicks field for the query"""
        pass

    @abstractmethod
    def _get_cost_field(self) -> str:
        """Get the cost field for the query"""
        pass

    @abstractmethod
    def _get_where_conditions(self) -> list[str]:
        """Get the WHERE clause for the query"""
        pass

    @abstractmethod
    def _get_from_clause(self) -> str:
        """Get the FROM clause for the query"""
        pass

    @abstractmethod
    def _get_join_clause(self) -> str:
        """Get the JOIN clause for the query"""
        pass

    @abstractmethod
    def _get_group_by_clause(self) -> str:
        """Get the GROUP BY clause for the query"""
        pass

    def _log_validation_errors(self, errors: list[str], warnings: list[str] | None = None):
        """Helper to log validation issues"""
        if errors:
            self.logger.error("Source validation failed", errors=errors, warnings=warnings or [])
        elif warnings:
            self.logger.warning("Source validation warnings", warnings=warnings)

    def _log_query_generation(self, success: bool, error: str | None = None):
        """Helper to log query generation status"""
        if success:
            self.logger.debug("Query generated successfully")
        else:
            self.logger.error("Query generation failed", error=error)

    def build_query(self) -> Optional[str]:
        """
        Build SQL query that returns marketing data in standardized format.

        MUST return columns in this exact order and format:
        - campaign_name (string): Campaign identifier
        - source_name (string): Source identifier
        - impressions (float): Number of impressions
        - clicks (float): Number of clicks
        - cost (float): Total cost in base currency

        Returns None if this source cannot provide data for the given context.
        """
        try:
            query = f"""
SELECT
    {self._get_campaign_name_field()} as {self.campaign_name_field},
    {self._get_source_name_field()} as {self.source_name_field},
    {self._get_impressions_field()} as {self.impressions_field},
    {self._get_clicks_field()} as {self.clicks_field},
    {self._get_cost_field()} as {self.cost_field}
{self._get_from_clause()}
{self._get_join_clause()}
{self._get_where_conditions()}
{self._get_group_by_clause()}"""

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
