"""
Facade contracts (DTOs) for experiments product.

These are framework-free frozen dataclasses that define the interface
between the experiments product and the rest of the system.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeatureFlagVariant:
    """Feature flag variant configuration."""

    key: str
    rollout_percentage: int
    name: str | None = None


@dataclass(frozen=True)
class CreateFeatureFlagInput:
    """Input for creating a feature flag (new format)."""

    key: str
    variants: tuple[FeatureFlagVariant, ...]
    name: str | None = None
    rollout_percentage: int | None = None
    aggregation_group_type_index: int | None = None
    ensure_experience_continuity: bool | None = None


@dataclass(frozen=True)
class CreateExperimentInput:
    """
    Input for creating an experiment.

    Supports both old format (parameters.feature_flag_variants)
    and new format (feature_flag_filters).

    Note: This class is NOT hashable when parameters is non-None due to the
    dict type. Use only feature_flag_filters (new format) if hashability is
    required for Turbo caching. The parameters field exists only for backwards
    compatibility during migration.
    """

    name: str
    feature_flag_key: str
    description: str = ""
    feature_flag_filters: CreateFeatureFlagInput | None = None
    parameters: dict[str, Any] | None = None


@dataclass(frozen=True)
class FeatureFlag:
    """Feature flag output."""

    id: int
    key: str
    active: bool
    created_at: datetime
    name: str | None = None


@dataclass(frozen=True)
class Experiment:
    """Experiment output."""

    id: int
    name: str
    feature_flag_id: int
    feature_flag_key: str
    is_draft: bool
    created_at: datetime
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    updated_at: datetime | None = None
