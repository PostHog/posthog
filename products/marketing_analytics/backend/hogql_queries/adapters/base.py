# Base Marketing Source Adapter

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
import structlog

from posthog.hogql import ast
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
    def _get_campaign_name_field_ast(self) -> ast.Expr:
        """Get the campaign name field expression as AST"""
        pass

    @abstractmethod
    def _get_source_name_field_ast(self) -> ast.Expr:
        """Get the source name field expression as AST"""
        pass

    @abstractmethod
    def _get_impressions_field_ast(self) -> ast.Expr:
        """Get the impressions field expression as AST"""
        pass

    @abstractmethod
    def _get_clicks_field_ast(self) -> ast.Expr:
        """Get the clicks field expression as AST"""
        pass

    @abstractmethod
    def _get_cost_field_ast(self) -> ast.Expr:
        """Get the cost field expression as AST"""
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
        Build SQL query that returns marketing data in standardized format using AST internally.

        MUST return columns in this exact order and format:
        - campaign_name (string): Campaign identifier
        - source_name (string): Source identifier
        - impressions (float): Number of impressions
        - clicks (float): Number of clicks
        - cost (float): Total cost in base currency

        Returns None if this source cannot provide data for the given context.
        """
        try:
            # Build SELECT columns using AST internally
            select_columns = [
                ast.Alias(alias=self.campaign_name_field, expr=self._get_campaign_name_field_ast()),
                ast.Alias(alias=self.source_name_field, expr=self._get_source_name_field_ast()),
                ast.Alias(alias=self.impressions_field, expr=self._get_impressions_field_ast()),
                ast.Alias(alias=self.clicks_field, expr=self._get_clicks_field_ast()),
                ast.Alias(alias=self.cost_field, expr=self._get_cost_field_ast()),
            ]

            # Build query components
            from_clause = self._get_from_clause()
            join_clause = self._get_join_clause()
            where_conditions = self._get_where_conditions()
            group_by_clause = self._get_group_by_clause()

            # Build the base SELECT statement using AST
            select_part = "SELECT\n    " + ",\n    ".join([col.to_hogql() for col in select_columns])

            # Assemble the complete query
            query_parts = [select_part]
            if from_clause:
                query_parts.append(from_clause)
            if join_clause:
                query_parts.append(join_clause)
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)
                query_parts.append(where_clause)
            if group_by_clause:
                query_parts.append(group_by_clause)

            query = "\n".join(query_parts)

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
