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
    def _get_where_conditions_ast(self) -> list[ast.Expr]:
        """Get WHERE condition expressions as AST"""
        pass

    @abstractmethod
    def _get_from_ast(self) -> ast.JoinExpr:
        """Get the FROM clause as AST JoinExpr"""
        pass

    @abstractmethod
    def _get_group_by_ast(self) -> list[ast.Expr]:
        """Get GROUP BY expressions as AST"""
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

    def build_query_ast(self) -> Optional[ast.SelectQuery]:
        """
        Build AST SelectQuery that returns marketing data in standardized format.

        MUST return columns in this exact order and format:
        - campaign_name (string): Campaign identifier
        - source_name (string): Source identifier
        - impressions (float): Number of impressions
        - clicks (float): Number of clicks
        - cost (float): Total cost in base currency

        Returns None if this source cannot provide data for the given context.
        """
        try:
            # Build SELECT columns using AST
            select_columns = [
                ast.Alias(alias=self.campaign_name_field, expr=self._get_campaign_name_field_ast()),
                ast.Alias(alias=self.source_name_field, expr=self._get_source_name_field_ast()),
                ast.Alias(alias=self.impressions_field, expr=self._get_impressions_field_ast()),
                ast.Alias(alias=self.clicks_field, expr=self._get_clicks_field_ast()),
                ast.Alias(alias=self.cost_field, expr=self._get_cost_field_ast()),
            ]

            # Build query components using AST
            from_expr = self._get_from_ast()
            where_conditions = self._get_where_conditions_ast()
            group_by_exprs = self._get_group_by_ast()

            # Build WHERE clause
            where_expr = None
            if where_conditions:
                if len(where_conditions) == 1:
                    where_expr = where_conditions[0]
                else:
                    where_expr = ast.And(exprs=where_conditions)

            # Build GROUP BY clause
            group_by = group_by_exprs if group_by_exprs else None

            # Create the complete AST SelectQuery
            query = ast.SelectQuery(
                select=select_columns,
                select_from=from_expr,
                where=where_expr,
                group_by=group_by
            )

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None

    def build_query(self) -> Optional[str]:
        """
        Build SQL query string (backwards compatibility).
        """
        query_ast = self.build_query_ast()
        return query_ast.to_hogql() if query_ast else None
