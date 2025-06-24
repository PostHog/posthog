# Base Marketing Source Adapter

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of source validation"""
    is_valid: bool
    errors: List[str]
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass 
class QueryContext:
    """Context needed for query building"""
    date_range: Any  # QueryDateRange
    team: Any
    global_filters: List[Any] = None
    base_currency: str = 'USD'
    
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
    
    def __init__(self, team: Any, config: Dict[str, Any]):
        self.team = team
        self.config = config
        self.logger = logger.bind(
            source_type=self.get_source_type(),
            team_id=team.pk if team else None
        )
    
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
    def build_query(self, context: QueryContext) -> Optional[str]:
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
        pass
    
    def get_required_permissions(self) -> List[str]:
        """Return list of permissions/credentials needed for this source"""
        return []
    
    def get_description(self) -> str:
        """Return human-readable description of this source"""
        return f"{self.get_source_type()} marketing source adapter"
    
    def _log_validation_errors(self, errors: List[str], warnings: List[str] = None):
        """Helper to log validation issues"""
        if errors:
            self.logger.error("Source validation failed", errors=errors, warnings=warnings or [])
        elif warnings:
            self.logger.warning("Source validation warnings", warnings=warnings)
    
    def _log_query_generation(self, success: bool, error: str = None):
        """Helper to log query generation status"""
        if success:
            self.logger.debug("Query generated successfully")
        else:
            self.logger.error("Query generation failed", error=error) 