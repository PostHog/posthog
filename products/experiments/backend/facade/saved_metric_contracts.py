"""
Facade contracts (DTOs) for experiment saved metrics.

These are framework-free frozen dataclasses that define the interface
for saved metric operations.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CreateSavedMetricInput:
    """Input for creating a saved metric."""

    name: str
    query: dict[str, Any]
    description: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class UpdateSavedMetricInput:
    """Input for updating a saved metric."""

    name: str | None = None
    description: str | None = None
    query: dict[str, Any] | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class ListSavedMetricsInput:
    """Input for listing saved metrics with optional filtering."""

    # No filters for now - we'll add if needed in future PRs
    pass


@dataclass(frozen=True)
class ExperimentSavedMetric:
    """Saved metric output DTO."""

    id: int
    name: str
    query: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    created_by_id: int | None = None
    tags: list[str] | None = None
